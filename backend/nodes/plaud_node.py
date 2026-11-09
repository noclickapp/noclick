"""Plaud workspace reads and Embedded device/upload operations.

Contracts: https://docs.plaud.ai/openapi/{enterprise,binding,file}.json (0.0.1).
Tokens are pasted, never minted or refreshed. Workspace and Embedded tokens
are deliberately distinct; upload operations return URLs without fetching them.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

WORKSPACE = "plaud_workspace_token"
EMBEDDED = "plaud_user_token"
PARTNER_BASES = {"us": "https://platform-us.plaud.ai/developer/api", "jp": "https://platform-jp.plaud.ai/developer/api"}
WORKSPACE_BASE = "https://api.plaud.ai"


class _Credential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class PlaudWorkspaceCredential(_Credential):
    model_config = ConfigDict(title="Plaud Workspace Token", json_schema_extra={
        "x-credential-url": "https://docs.plaud.ai/openapi/enterprise.json",
        "x-credential-instructions": "Paste an existing US workspace access token from Plaud's workspace token endpoint. Tokens expire after one hour; replace the token when it expires. Connection reads your own workspace. Japan workspace endpoints are not supported by this credential."})
    credential_type: Literal["plaud_workspace_token"] = Field(WORKSPACE, json_schema_extra={"ui:hidden": True})


class PlaudUserCredential(_Credential):
    model_config = ConfigDict(title="Plaud Embedded User Token", json_schema_extra={
        "x-credential-url": "https://docs.plaud.ai/plaud-embedded/auth-api-overview",
        "x-credential-instructions": "Paste an existing Embedded user access token, not a partner token. Choose the token's region and enter a device serial number for the read-only binding check. Replace expired tokens yourself. Binding reads prove token acceptance, not device ownership."})
    credential_type: Literal["plaud_user_token"] = Field(EMBEDDED, json_schema_extra={"ui:hidden": True})
    region: Literal["us", "jp"] = Field("us", title="API region")
    device_sn: str = Field(..., min_length=1, max_length=128, title="Device serial number", description="A device SN for the read-only connection check (881 = Note Pro, 882 = NotePin S).", pattern=r"^(881|882)[0-9]+$")


Credential = Union[PlaudWorkspaceCredential, PlaudUserCredential]


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ListWorkspaces(_Input):
    """Read the workspace belonging to the supplied US workspace token."""
    operation: Literal["list_workspaces"] = "list_workspaces"


class ListMembers(_Input):
    """Read one page of members, including inactive members."""
    operation: Literal["list_members"] = "list_members"
    limit: int = Field(100, ge=1, le=1000)
    cursor: str | None = Field(None, max_length=4096, description="Use next_cursor from the previous page.")


class ListFileChanges(ListMembers):
    """Read one page of changed recordings; retain next_checkpoint to resume."""
    operation: Literal["list_file_changes"] = "list_file_changes"
    checkpoint: str | None = Field(None, max_length=4096)


class GetFile(_Input):
    """Read recording metadata."""
    operation: Literal["get_file"] = "get_file"
    file_id: str = Field(..., min_length=1, max_length=512, description="Recording ID from the file change feed.")

    @field_validator("file_id")
    @classmethod
    def single_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a recording ID without path traversal or control characters")
        return value


class GetFileTranscript(GetFile):
    """Read the recording's speaker-labelled transcript."""
    operation: Literal["get_file_transcript"] = "get_file_transcript"


class GetFileSummaries(GetFile):
    """Read all generated summaries for a recording."""
    operation: Literal["get_file_summaries"] = "get_file_summaries"


class GetFileAudio(GetFile):
    """Get the expiring audio URL, without downloading the audio."""
    operation: Literal["get_file_audio"] = "get_file_audio"


class GetDeviceBinding(_Input):
    """Read remote device binding and app history; this does not prove ownership."""
    operation: Literal["get_device_binding"] = "get_device_binding"
    sn: str = Field(..., min_length=1, max_length=128, description="Device serial number.")
    type: Literal["notepro", "notepins"] = Field("notepro", description="Use notepro for SN prefix 881, notepins for 882.")


class BindDevice(GetDeviceBinding):
    """Register a device/owner association in the Plaud cloud registry."""
    operation: Literal["bind_device"] = "bind_device"


class UnbindDevice(GetDeviceBinding):
    """Remove the cloud binding. Also call depair(clear: true) in the device SDK to clear the local BLE binding."""
    operation: Literal["unbind_device"] = "unbind_device"


class GeneratePresignedUrls(_Input):
    """Generate multipart upload URLs. Upload the raw chunks separately and keep each ETag."""
    operation: Literal["generate_presigned_urls"] = "generate_presigned_urls"
    filesize: int = Field(..., gt=0, description="Full audio size in bytes; Plaud returns one URL per 5 MB part.")
    filetype: Literal["mp3", "opus"] = "mp3"


class UploadPart(BaseModel):
    PartNumber: int = Field(..., ge=1)
    ETag: str = Field(..., min_length=1, max_length=1024, description="Exact ETag returned by the S3 PUT, including quotes.")


class CompleteUpload(_Input):
    """Finalize previously uploaded parts. The returned download URL lasts 24 hours."""
    operation: Literal["complete_upload"] = "complete_upload"
    file_id: str = Field(..., min_length=1, max_length=512)
    upload_id: str = Field(..., min_length=1, max_length=4096)
    part_list: list[UploadPart] = Field(..., min_length=1, max_length=10000)
    filetype: Literal["mp3", "opus"] = "mp3"
    file_md5: str | None = Field(None, pattern=r"^[a-fA-F0-9]{32}$")


Config = Annotated[Union[ListWorkspaces, ListMembers, ListFileChanges, GetFile,
    GetFileTranscript, GetFileSummaries, GetFileAudio, GetDeviceBinding,
    BindDevice, UnbindDevice, GeneratePresignedUrls, CompleteUpload], Field(discriminator="operation")]


class PlaudFullConfig(NodeConfig[Config, Credential]):
    pass


# One and only one provider operation for each public operation.
ROUTES = {
    "list_workspaces": ("GET", "/team-api-integration/v1/team/workspaces", WORKSPACE),
    "list_members": ("GET", "/team-api-integration/v1/team/members", WORKSPACE),
    "list_file_changes": ("GET", "/team-api-integration/v1/team-files/items", WORKSPACE),
    "get_file": ("GET", "/team-api-integration/v1/team-files/items/{id}", WORKSPACE),
    "get_file_transcript": ("GET", "/team-api-integration/v1/team-files/items/{id}/transcript", WORKSPACE),
    "get_file_summaries": ("GET", "/team-api-integration/v1/team-files/items/{id}/summaries", WORKSPACE),
    "get_file_audio": ("GET", "/team-api-integration/v1/team-files/items/{id}/audio", WORKSPACE),
    "get_device_binding": ("GET", "/open/partner/sdk/binding", EMBEDDED),
    "bind_device": ("POST", "/open/partner/sdk/bind", EMBEDDED),
    "unbind_device": ("POST", "/open/partner/sdk/unbind", EMBEDDED),
    "generate_presigned_urls": ("POST", "/open/partner/files/upload/generate-presigned-urls", EMBEDDED),
    "complete_upload": ("POST", "/open/partner/files/upload/complete-upload", EMBEDDED),
}


class PlaudNode(WorkflowNode):
    integration_type = "automation-plaud"
    credential_provider_labels = {"plaud": "Plaud"}
    # Connection-only loader: no config exists at connect time. Workspace tokens
    # return the account's workspace. Embedded tokens read the supplied SN; the
    # published binding API cannot establish ownership, so claim reachability.
    connection_evidence = ConnectionEvidence(field="connection", noun="Plaud access", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return PlaudFullConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type") not in {None, WORKSPACE, EMBEDDED}:
            raise ValueError("Attach a Plaud credential")
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type") not in {None, WORKSPACE, EMBEDDED}:
            return {"valid": False, "errors": ["Attach a Plaud credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name != "connection":
            raise ValueError("Unknown Plaud connection field")
        credential = TypeAdapter(Credential).validate_python(credential_data)
        if isinstance(credential, PlaudWorkspaceCredential):
            config = ListWorkspaces()
        else:
            config = GetDeviceBinding(sn=credential.device_sn, type="notepro" if credential.device_sn.startswith("881") else "notepins")
        from nodes.core.registry import NodeFactory
        node = NodeFactory.create_node(node_id="plaud-connection", node_type=cls.integration_type,
            node_data={"config": config.model_dump(), "credentials": credential.model_dump()})
        result = await node.execute({})
        if result.get("status") == "error":
            return result
        if isinstance(credential, PlaudWorkspaceCredential):
            rows = result["data"].get("workspaces", [])
            return {"options": [{"value": r["workspace_id"], "label": r.get("name") or r["workspace_id"]} for r in rows], "next_page_token": None}
        # Do not claim that another application's bound device is this user's.
        return {"options": [], "next_page_token": None}

    async def execute(self, inputs):
        if not isinstance(self.config, PlaudFullConfig) or self.config.credentials is None:
            raise ValueError("Attach a Plaud token credential")
        config, credential = self.config.config, self.config.credentials
        method, path, family = ROUTES[config.operation]
        if credential.credential_type != family:
            raise ValueError("This operation requires a Plaud workspace token" if family == WORKSPACE else "This operation requires a Plaud Embedded user token")
        base = WORKSPACE_BASE if family == WORKSPACE else PARTNER_BASES[credential.region]
        params = {}
        body = None
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", quote(config.file_id, safe=""))
        elif method == "GET":
            params = values
        else:
            body = values
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, base + path, params=params,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json", "Content-Type": "application/json"},
                **({"json": body} if body is not None else {}))
        if response.status_code >= 400:
            # Preserve provider rejection text for the shared connection seam.
            try:
                error = response.json()
                message = error.get("msg") or error.get("message") if isinstance(error, dict) else None
            except ValueError:
                message = None
            return {"status": "error", "http_status": response.status_code,
                "error": str(message or "Plaud request failed").replace(credential.access_token, "[redacted]")[:2000]}
        response.raise_for_status()
        if len(response.content) > 20_000_000:
            raise ValueError("Plaud response exceeds the supported JSON size")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected a Plaud JSON object")
        if data.get("type") == "error" or (isinstance(data.get("status"), int) and data["status"] >= 400):
            return {"status": "error", "http_status": data.get("status"),
                "error": str(data.get("msg") or "Plaud rejected the request").replace(credential.access_token, "[redacted]")[:2000]}
        # Preserve pagination, checkpoints, utterances and the provider's casing.
        return {"status": "success", "operation": config.operation, "data": data.get("data", data)}

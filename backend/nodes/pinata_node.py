"""Pinata file, group and IPFS automation using a manually supplied JWT.

Each operation makes one documented API request; paginated reads return one page.
Writes report provider acknowledgement, without claiming asynchronous pin completion.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class PinataJWTCredential(BaseModel):
    model_config = ConfigDict(title="Pinata JWT", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.pinata.cloud/developers/api-keys",
        "x-credential-instructions": "Create a Pinata API key and paste its JWT. Grant file and group read/write permissions for the operations you use. Legacy JSON pinning and usage require the corresponding IPFS permissions. NoClick sends it only to api.pinata.cloud. Listing public-network files proves account read access, not every write permission.",
    })
    credential_type: Literal["pinata_jwt"] = Field("pinata_jwt", json_schema_extra={"ui:hidden": True})
    jwt: str = Field(..., title="JWT", min_length=1, max_length=16384, json_schema_extra={"ui:widget": "password"})

    @field_validator("jwt", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="JWT")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the JWT without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Network(Input):
    network: Literal["public", "private"] = Field("public", description="Pinata network containing the resource.")


class Page(Network):
    limit: int = Field(10, ge=1, le=1000, description="One page only; use next_page_token to continue.")
    page_token: str | None = Field(None, max_length=4096)


# Path identifiers are single segments, never a user-selected destination URL.
Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


class ListFiles(Page):
    operation: Literal["list_files"] = "list_files"
    name: str | None = None
    group: str | None = Field(None, description="Group ID, or the string null for ungrouped files.")
    mime_type: str | None = None
    cid: str | None = None
    cid_pending: bool | None = None
    order: Literal["ASC", "DESC"] | None = None
    metadata: dict[str, str] | None = None


class File(Network):
    file_id: Identifier


class GetFile(File):
    operation: Literal["get_file"] = "get_file"


class UpdateFile(File):
    operation: Literal["update_file"] = "update_file"
    name: str | None = Field(None, min_length=1, max_length=1024)
    keyvalues: dict[str, str] | None = None

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.keyvalues is None:
            raise ValueError("Supply a name or keyvalues to update")
        return self


class DeleteFile(File):
    operation: Literal["delete_file"] = "delete_file"


class PinByCID(Input):
    operation: Literal["pin_by_cid"] = "pin_by_cid"
    cid: Identifier
    name: str | None = None
    group_id: Identifier | None = None
    keyvalues: dict[str, str] | None = None
    host_nodes: list[str] | None = None


class ListPinRequests(Input):
    operation: Literal["list_pin_requests"] = "list_pin_requests"
    order: Literal["ASC", "DESC"] | None = None
    status: Literal["prechecking", "backfilled", "retreiving", "expired", "searching", "over_free_limit", "over_max_size", "invalid_object", "bad_host_node"] | None = None
    cid: str | None = None
    limit: int = Field(10, ge=1, le=1000)
    page_token: str | None = Field(None, max_length=4096)


class CancelPinRequest(Input):
    operation: Literal["cancel_pin_request"] = "cancel_pin_request"
    request_id: Identifier


class CreateDownloadLink(Input):
    operation: Literal["create_download_link"] = "create_download_link"
    url: str = Field(..., description="Private file URL on your Pinata gateway. Only signed, never fetched by NoClick.")
    date: int = Field(..., ge=0, description="Unix signing timestamp in seconds.")
    expires: int = Field(3600, ge=1, description="Link lifetime in seconds.")
    method: Literal["GET"] = "GET"

    @field_validator("url")
    @classmethod
    def gateway_url(cls, value):
        if not re.fullmatch(r"https://[a-zA-Z0-9-]+\.mypinata\.cloud/files/[A-Za-z0-9]+", value):
            raise ValueError("Use https://your-gateway.mypinata.cloud/files/CID")
        return value


class CreateGroup(Network):
    operation: Literal["create_group"] = "create_group"
    name: str = Field(..., min_length=1, max_length=1024)
    is_public: bool | None = None


class ListGroups(Page):
    operation: Literal["list_groups"] = "list_groups"
    name: str | None = None
    is_public: bool | None = None


class Group(Network):
    group_id: Identifier


class GetGroup(Group):
    operation: Literal["get_group"] = "get_group"


class UpdateGroup(Group):
    operation: Literal["update_group"] = "update_group"
    name: str | None = Field(None, min_length=1, max_length=1024)
    is_public: bool | None = None

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.is_public is None:
            raise ValueError("Supply a name or visibility to update")
        return self


class DeleteGroup(Group):
    operation: Literal["delete_group"] = "delete_group"


class AddFileToGroup(Group):
    operation: Literal["add_file_to_group"] = "add_file_to_group"
    file_id: Identifier


class RemoveFileFromGroup(Group):
    operation: Literal["remove_file_from_group"] = "remove_file_from_group"
    file_id: Identifier


class Swap(Network):
    cid: Identifier


class AddSwap(Swap):
    operation: Literal["add_swap"] = "add_swap"
    swap_cid: Identifier


class GetSwapHistory(Swap):
    operation: Literal["get_swap_history"] = "get_swap_history"
    domain: str = Field(..., min_length=1, max_length=253, description="Gateway domain with the Hot Swaps plugin installed.")


class RemoveSwap(Swap):
    operation: Literal["remove_swap"] = "remove_swap"


class TestAuthentication(Input):
    operation: Literal["test_authentication"] = "test_authentication"


class GetDataUsage(Input):
    operation: Literal["get_data_usage"] = "get_data_usage"


class PinJSON(Input):
    operation: Literal["pin_json"] = "pin_json"
    content: dict[str, Any] = Field(..., description="JSON object to pin to the public IPFS network.")
    name: str | None = None
    keyvalues: dict[str, str] | None = None
    cid_version: Literal[0, 1] = 1


PinataOperation = Annotated[Union[ListFiles, GetFile, UpdateFile, DeleteFile, PinByCID,
    ListPinRequests, CancelPinRequest, CreateDownloadLink, CreateGroup, ListGroups,
    GetGroup, UpdateGroup, DeleteGroup, AddFileToGroup, RemoveFileFromGroup,
    AddSwap, GetSwapHistory, RemoveSwap, TestAuthentication, GetDataUsage, PinJSON], Field(discriminator="operation")]


class PinataConfig(NodeConfig[PinataOperation, PinataJWTCredential]):
    pass


def request_for(op):
    """Map a typed operation to exactly one pinned API operation."""
    values = op.model_dump(exclude_none=True)
    action = values.pop("operation")
    network = values.pop("network", "public")
    path, method, params, body = "", "GET", {}, None
    enc = lambda value: quote(value, safe="")
    if action in {"test_authentication", "get_data_usage", "pin_json"}:
        path = {"test_authentication": "/data/testAuthentication", "get_data_usage": "/data/userPinnedDataTotal", "pin_json": "/pinning/pinJSONToIPFS"}[action]
        if action == "pin_json":
            method = "POST"
            body = {"pinataContent": op.content, "pinataOptions": {"cidVersion": op.cid_version}}
            metadata = {k: values[k] for k in ("name", "keyvalues") if k in values}
            if metadata: body["pinataMetadata"] = metadata
        return method, path, params, body
    if action in {"list_files", "get_file", "update_file", "delete_file"}:
        path = f"/files/{network}"
        if action != "list_files": path += "/" + enc(values.pop("file_id"))
        if action == "list_files":
            rename = {"page_token": "pageToken", "mime_type": "mimeType", "cid_pending": "cidPending"}
            params = {rename.get(k, k): v for k, v in values.items() if k != "metadata"}
            params.update({f"metadata[{k}]": v for k, v in (op.metadata or {}).items()})
        elif action == "update_file": method, body = "PUT", values
        elif action == "delete_file": method = "DELETE"
    elif action in {"pin_by_cid", "list_pin_requests", "cancel_pin_request"}:
        path = "/files/public/pin_by_cid"
        if action == "pin_by_cid": method, body = "POST", values
        elif action == "cancel_pin_request": method, path = "DELETE", path + "/" + enc(op.request_id)
        else: params = {"pageToken" if k == "page_token" else k: v for k, v in values.items()}
    elif action == "create_download_link":
        method, path, body = "POST", "/files/private/download_link", values
    elif action in {"add_swap", "get_swap_history", "remove_swap"}:
        path = f"/files/{network}/swap/" + enc(op.cid)
        if action == "add_swap": method, body = "PUT", {"swapCid": op.swap_cid}
        elif action == "remove_swap": method = "DELETE"
        else: params = {"domain": op.domain}
    else:
        path = f"/groups/{network}"
        if action not in {"create_group", "list_groups"}: path += "/" + enc(values.pop("group_id"))
        if action in {"add_file_to_group", "remove_file_from_group"}:
            path += "/ids/" + enc(op.file_id)
            method = "PUT" if action == "add_file_to_group" else "DELETE"
        elif action == "list_groups": params = {{"page_token": "pageToken", "is_public": "isPublic"}.get(k, k): v for k, v in values.items()}
        elif action == "create_group": method, body = "POST", values
        elif action == "update_group": method, body = "PUT", values
        elif action == "delete_group": method = "DELETE"
    return method, "/v3" + path, params, body


class PinataNode(WorkflowNode):
    integration_type = "automation-pinata"
    connection_evidence = ConnectionEvidence(noun="files", operation="list_files", label_keys=("name", "cid", "id"))

    @classmethod
    def get_config_model(cls):
        return PinataConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Pinata JWT")
        token = self.config.credentials.jwt
        op = self.config.config
        method, path, params, body = request_for(op)
        # HTTP query booleans use the documented lowercase representation.
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.pinata.cloud" + path,
                    params=params, json=body, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
            if not 200 <= response.status_code < 300:
                # Preserve provider rejection text for the shared credential seam.
                message = response.text[:4000].replace(token, "[redacted]")
                result = {"status": "error", "http_status": response.status_code, "message": message,
                          "write_outcome": "unverified" if method != "GET" else None}
            else:
                if len(response.content) > 10_000_000:
                    raise ValueError("Pinata response exceeds the supported size")
                payload = response.json() if response.content else {"data": None}
                if not isinstance(payload, dict) or any(payload.get(k) for k in ("error", "errors")):
                    raise ValueError("Unexpected Pinata response")
                result = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": payload.get("data", payload)}
                row_key = {"list_files": "files", "list_groups": "groups", "list_pin_requests": "jobs"}.get(op.operation)
                if row_key:
                    data = payload.get("data")
                    if not isinstance(data, dict) or not isinstance(data.get(row_key), list):
                        raise ValueError("Unexpected Pinata page")
                    following = data.get("next_page_token")
                    if following is not None and not isinstance(following, str):
                        raise ValueError("Unexpected Pinata continuation")
                    result.update(items=data[row_key], next_page_token=following or None, has_more=bool(following))
                if method != "GET":
                    result["acknowledged"] = True
                # A pin request acknowledgement is not proof that IPFS retrieval finished.
                if op.operation == "pin_by_cid": result["pin_completion_verified"] = False
        except (httpx.HTTPError, ValueError, TypeError):
            result = {"status": "error", "message": "Pinata request or response could not be verified",
                      "write_outcome": "unverified" if method != "GET" else None}
        # Providers may echo input in errors or metadata; never expose the credential.
        result = json.loads(json.dumps(result).replace(token, "[redacted]"))
        await self.emit(result)
        return result

"""Bika's published OpenAPI: account reads and v2 database record automation.

Contract: https://bika.ai/api/openapi/bika/openapi.json (2.0.17-release.0).
Token setup: https://bika.ai/help/guide/developer/openapi.
Each operation issues one request; list_records returns the provider's offset
for an explicit next-page call. Writes are never automatically retried.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://bika.ai/api/openapi/bika"
FAMILY = "bika_api_token"
NODE_TYPE = "automation-bika"
ResourceID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_*.-]*$")]


class BikaAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        extra="ignore", hide_input_in_errors=True, title="Bika API Token",
        json_schema_extra={
            "x-credential-url": "https://bika.ai/help/guide/developer/openapi",
            "x-credential-instructions": "Copy your API token from Bika user settings and paste it here. The token is sent as a Bearer token to bika.ai. Access depends on your account's workspace and database permissions.",
        },
    )
    credential_type: Literal["bika_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListSpaces(_Input):
    """List the workspaces accessible to this account."""
    operation: Literal["list_spaces"] = "list_spaces"


class GetSpace(_Input):
    """Get details of one workspace."""
    operation: Literal["get_space"] = "get_space"
    space_id: ResourceID = Field(..., title="Space ID", description="Copy the spc… ID from the workspace URL.")


class GetProfile(_Input):
    """Read the authenticated user's profile."""
    operation: Literal["get_profile"] = "get_profile"


class _Database(_Input):
    space_id: ResourceID = Field(..., title="Space ID", description="Copy the spc… ID from the workspace URL.")
    database_id: ResourceID = Field(..., title="Database ID", description="The dat… node ID in the database URL.")


class _Record(_Database):
    record_id: ResourceID = Field(..., title="Record ID")


class ListRecords(_Database):
    """Read one page; pass next_offset into offset to continue."""
    operation: Literal["list_records"] = "list_records"
    page_size: int = Field(100, ge=1, le=100, title="Page size")
    offset: str | None = Field(None, max_length=4096, description="Opaque offset returned by the previous page; omit for the first page.")
    max_records: int | None = Field(None, ge=1, description="Optional provider limit on records returned.")
    fields: list[str] | None = Field(None, description="Only return these field names or IDs.")
    filter: str | None = Field(None, max_length=10000, description='Bika filter expression, for example field1=="value1";field2>10. Sent with URL encoding.')
    field_key: Literal["name", "id"] = Field("name", title="Field key")


class GetRecord(_Record):
    """Get one record with structured JSON cell values."""
    operation: Literal["get_record"] = "get_record"
    field_key: Literal["name", "id"] = Field("name", title="Field key")


class CreateRecordFields(_Input):
    fields: dict[str, Any] = Field(..., description="Cell values keyed by field name or ID. Use Bika's documented cell-value formats.")


class UpdateRecordFields(CreateRecordFields):
    id: ResourceID = Field(..., title="Record ID")


class CreateRecords(_Database):
    """Create up to ten records in one request."""
    operation: Literal["create_records"] = "create_records"
    field_key: Literal["name", "id"] = Field("name", title="Field key")
    records: list[CreateRecordFields] = Field(..., min_length=1, max_length=10)


class UpdateRecords(_Database):
    """Update up to ten records in one request."""
    operation: Literal["update_records"] = "update_records"
    field_key: Literal["name", "id"] = Field("name", title="Field key")
    records: list[UpdateRecordFields] = Field(..., min_length=1, max_length=10)


class UpdateRecord(_Record):
    """Update selected fields of one record."""
    operation: Literal["update_record"] = "update_record"
    field_key: Literal["name", "id"] = Field("name", title="Field key")
    fields: dict[str, Any] = Field(..., description="Fields to update; null clears a cell where supported by Bika.")


class DeleteRecords(_Database):
    """Delete up to ten explicitly named records."""
    operation: Literal["delete_records"] = "delete_records"
    record_ids: list[ResourceID] = Field(..., min_length=1, max_length=10, title="Record IDs")


class DeleteRecord(_Record):
    """Delete one explicitly named record."""
    operation: Literal["delete_record"] = "delete_record"


BikaConfig = Annotated[Union[ListSpaces, GetSpace, GetProfile, ListRecords, GetRecord,
    CreateRecords, UpdateRecords, UpdateRecord, DeleteRecords, DeleteRecord], Field(discriminator="operation")]


class BikaFullConfig(NodeConfig[BikaConfig, BikaAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class BikaNode(WorkflowNode):
    integration_type = "automation-bika"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_spaces", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return BikaFullConfig

    @staticmethod
    def _request_parts(op):
        action, method, params, body = op.operation, "GET", {}, None
        if action == "list_spaces":
            return method, "/v1/spaces", params, body
        if action == "get_profile":
            return method, "/v1/user/profile", params, body
        path = "/v1/spaces/" + quote(op.space_id, safe="")
        if action == "get_space":
            return method, path, params, body
        path = "/v2/spaces/" + quote(op.space_id, safe="") + "/resources/databases/" + quote(op.database_id, safe="") + "/records"
        if isinstance(op, _Record):
            path += "/" + quote(op.record_id, safe="")
        if action in {"list_records", "get_record"}:
            params = {"fieldKey": op.field_key, "cellFormat": "json"}
            if action == "list_records":
                params["pageSize"] = op.page_size
                for field, wire in [("offset", "offset"), ("max_records", "maxRecords"), ("fields", "fields"), ("filter", "filter")]:
                    if (value := getattr(op, field)) is not None:
                        params[wire] = value
        elif action in {"create_records", "update_records"}:
            method = "POST" if action == "create_records" else "PUT"
            body = {"fieldKey": op.field_key, "records": [r.model_dump() for r in op.records]}
        elif action == "update_record":
            method, body = "PUT", {"fieldKey": op.field_key, "fields": op.fields}
        else:
            method = "DELETE"
            if action == "delete_records":
                # OpenAPI query arrays default to form/explode=true (repeated keys).
                params = {"records": op.record_ids}
        return method, path, params, body

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Bika API token")
        op, credential = self.config.config, self.config.credentials
        method, path, params, body = self._request_parts(op)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"})
        except (httpx.HTTPError, SSRFError):
            raise ValueError("Bika request could not be completed; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                rejected = response.json()
                message = rejected.get("message") if isinstance(rejected, dict) else None
            except ValueError:
                message = None
            if isinstance(message, str) and message:
                raise ValueError(f"Bika HTTP {response.status_code}: " + _redact(message, credential.api_token))
            raise ValueError(f"Bika rejected the request (HTTP {response.status_code})")
        if len(response.content) > 10_000_000:
            raise ValueError("Bika response exceeds the supported size")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Bika returned an invalid JSON response; inspect writes before retrying") from None
        if not isinstance(payload, dict):
            raise ValueError("Bika returned an unexpected response")
        if op.operation == "get_profile":
            if not isinstance(payload.get("id"), str) or not isinstance(payload.get("name"), str):
                raise ValueError("Bika did not return an account profile")
            data = payload
        else:
            if payload.get("success") is not True or payload.get("code") != 200 or "data" not in payload:
                if payload.get("success") is False and isinstance(payload.get("message"), str):
                    raise ValueError("Bika error " + str(payload.get("code")) + ": " + _redact(payload["message"], credential.api_token))
                raise ValueError("Bika did not confirm the operation; inspect writes before retrying")
            data = payload["data"]
        if op.operation == "list_spaces" and not isinstance(data, list):
            raise ValueError("Bika did not return a workspace list")
        if op.operation == "get_space" and (not isinstance(data, dict) or data.get("id") != op.space_id):
            raise ValueError("Bika did not return the requested workspace")
        if op.operation in {"get_record", "update_record"}:
            self._record(data, expected_id=op.record_id)
        if op.operation in {"create_records", "update_records"}:
            rows = data.get("records") if isinstance(data, dict) else None
            if not isinstance(rows, list) or len(rows) != len(op.records):
                raise ValueError("Bika did not confirm every requested record; inspect before retrying")
            for row in rows:
                self._record(row)
            if op.operation == "update_records" and {r["id"] for r in rows} != {r.id for r in op.records}:
                raise ValueError("Bika did not confirm the requested record IDs; inspect before retrying")
        if op.operation in {"delete_record", "delete_records"}:
            rows = [data] if op.operation == "delete_record" else data
            expected_ids = [op.record_id] if op.operation == "delete_record" else op.record_ids
            if (not isinstance(rows, list) or len(rows) != len(expected_ids)
                or any(not isinstance(row, dict) or row.get("deleted") is not True for row in rows)
                or {row.get("id") for row in rows} != set(expected_ids)):
                raise ValueError("Bika did not confirm every requested deletion; inspect before retrying")
        result = {"status": "success", "operation": op.operation, "data": data}
        if op.operation == "list_records":
            if not isinstance(data, dict) or not isinstance(data.get("records"), list) or type(data.get("hasMore")) is not bool:
                raise ValueError("Bika returned an invalid record page")
            offset = data.get("offset")
            if data["hasMore"] and (not isinstance(offset, str) or not offset or offset == op.offset):
                raise ValueError("Bika did not return an advancing pagination offset")
            for row in data["records"]:
                self._record(row)
            result.update(next_offset=offset if data["hasMore"] else None, has_more=data["hasMore"])
        result = _redact(result, credential.api_token)
        await self.emit(result)
        return result

    @staticmethod
    def _record(row, expected_id=None):
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
            or not isinstance(row.get("fields"), dict)
            or not isinstance(row.get("createdAt"), str)
            or (expected_id is not None and row["id"] != expected_id)):
            raise ValueError("Bika returned an unexpected record; inspect writes before retrying")

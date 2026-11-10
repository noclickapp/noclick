"""Fun Generators UUID API: https://fungenerators.com/api/uuid/.

Current docs specify Bearer auth and GET /uuid/parse, unlike the pinned v1.5
OpenAPI. Both provider-authored response envelopes are supported.
"""
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.fungenerators.com"
DOCS_URL = "https://fungenerators.com/api/uuid/"


class FungeneratorsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Fun Generators API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS_URL,
            "x-credential-instructions": "Paste the API key from your Fun Generators subscription, without the Bearer prefix. UUID requests use your plan's quota. NoClick checks API reachability by generating one UUID; this service has no account identity endpoint.",
        })
    credential_type: Literal["fungenerators_api_key"] = Field("fungenerators_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ch.isspace() or ord(ch) < 33 or ord(ch) > 126 for ch in value):
            raise ValueError("Paste the API key without a header or spaces")
        return value


class GetUUIDsConfig(BaseModel):
    """Generate random UUIDs, optionally choosing a documented UUID version."""
    operation: Literal["get_uuids"] = Field("get_uuids", title="Generate UUIDs", json_schema_extra={"ui:hidden": True})
    limit: int = Field(1, ge=1, description="Number of UUIDs to generate. Your subscription limits apply.")
    version: Optional[Literal["0", "1", "2", "3", "4", "5", "6", "7"]] = Field(None,
        description="UUID version. Leave blank for random v4; 0 produces a nil UUID.")


class ParseUUIDConfig(BaseModel):
    """Check a UUID string's validity and return its version."""
    operation: Literal["parse_uuid"] = Field("parse_uuid", json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., min_length=1, description="UUID string to send to the provider for validation.")


FungeneratorsConfig = Annotated[Union[GetUUIDsConfig, ParseUUIDConfig], Field(discriminator="operation")]


class FungeneratorsFullConfig(NodeConfig[FungeneratorsConfig, FungeneratorsAPIKeyCredential]):
    pass


class FungeneratorsNode(WorkflowNode):
    integration_type = "automation-fungenerators"
    connection_evidence = ConnectionEvidence(operation="get_uuids", noun="generated UUIDs", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return FungeneratorsFullConfig

    @staticmethod
    def _error(response, api_key):
        try:
            body = response.json()
        except ValueError:
            return "Fun Generators returned HTTP " + str(response.status_code)
        error = body.get("error") if isinstance(body, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if isinstance(message, str) and message:
            return message.replace(api_key, "[redacted]")[:2000]
        return "Fun Generators did not confirm the request"

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Fun Generators API key")
        config = self.config.config
        if isinstance(config, GetUUIDsConfig):
            path = "/uuid"
            params = {"limit": config.limit}
            if config.version is not None:
                params["version"] = config.version
        else:
            path = "/uuid/parse"
            params = {"uuid": config.uuid}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.get(BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"})
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code,
                "error": self._error(response, credential.api_key)}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Fun Generators returned an invalid JSON response") from None
        if not isinstance(body, dict) or "error" in body:
            return {"status": "error", "error": self._error(response, credential.api_key)}
        contents = body.get("contents")
        if isinstance(contents, dict) and isinstance(contents.get("uuid"), list):
            rows = contents["uuid"]
        elif isinstance(config, GetUUIDsConfig) and isinstance(contents, list):
            rows = contents
        elif isinstance(config, ParseUUIDConfig) and isinstance(contents, dict):
            rows = [contents]
        else:
            raise ValueError("Fun Generators response is missing UUID results")
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Fun Generators returned invalid UUID results")
        items = []
        for row in rows:
            if isinstance(config, ParseUUIDConfig):
                valid = row.get("valid", row.get("is_valid"))
                if type(valid) is not bool:
                    raise ValueError("Fun Generators response is missing the validity verdict")
                item = {"uuid": row.get("uuid", config.uuid), "valid": valid}
                if row.get("version") is not None:
                    item["version"] = row["version"]
            else:
                if not isinstance(row.get("uuid"), str) or not row["uuid"] or "version" not in row:
                    raise ValueError("Fun Generators response is missing UUID or version")
                item = {"uuid": row["uuid"], "version": row["version"]}
            items.append(item)
        # The current examples' success.total disagrees with the number of rows.
        return {"status": "success", "items": items, "count": len(items)}

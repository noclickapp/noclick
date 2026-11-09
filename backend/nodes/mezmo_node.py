"""Automate the ten operations in Mezmo's published Enterprise API v3.

Uses a pasted enterprise access key and fixed provider routes. Native response
metadata and bulk per-item outcomes are preserved for downstream workflows.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.mezmo.com"
ROUTES = {
    "get_enterprise": ("GET", "/v3/enterprise"),
    "bulk_account_operations": ("PATCH", "/v3/enterprise/account"),
    "create_account": ("POST", "/v3/enterprise/account"),
    "get_account": ("GET", "/v3/enterprise/account/{account_id}"),
    "attach_account": ("PATCH", "/v3/enterprise/account/{account_id}/attach"),
    "detach_account": ("PATCH", "/v3/enterprise/account/{account_id}/detach"),
    "list_pipelines": ("GET", "/v3/enterprise/pipeline"),
    "get_pipeline_health": ("GET", "/v3/enterprise/pipeline/metric/health"),
    "get_pipeline_usage": ("GET", "/v3/enterprise/pipeline/metric/usage"),
    "get_pipeline_node_schemas": ("GET", "/v3/enterprise/pipeline/node"),
}


class MezmoAccessKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Mezmo Access Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.mezmo.com/docs/api",
            "x-credential-instructions": "Paste a Mezmo enterprise access key with permission for the operations you use. Create an enterprise service account access key in Mezmo, or use a personal access key with enterprise access. Paste only the key, without the Token prefix. NoClick checks it by reading your enterprise and child accounts.",
        },
    )
    credential_type: Literal["mezmo_access_key"] = Field("mezmo_access_key", json_schema_extra={"ui:hidden": True})
    access_key: str = Field(..., title="Access key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Access key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class MezmoGetEnterpriseConfig(_Input):
    """Get your enterprise identity and its child accounts."""
    operation: Literal["get_enterprise"] = "get_enterprise"


class MezmoPlan(_Input):
    type: str = Field(..., min_length=4, max_length=50, description="Billing plan type, for example enterprise.")


class MezmoAccountFields(_Input):
    company: str | None = Field(None, max_length=250)
    owneremail: EmailStr | None = Field(None, max_length=320, title="Owner email")
    external_id: str | None = Field(None, max_length=255)
    plan: MezmoPlan | None = None
    retention: int | None = Field(None, ge=0, le=90, description="Log retention in days.")
    enable_syslog: StrictBool | None = None
    include_admins: StrictBool | None = None

    @model_validator(mode="after")
    def non_nullable_fields(self):
        if any(getattr(self, key) is None for key in self.model_fields_set - {"external_id"}):
            raise ValueError("Only external_id accepts an explicit null")
        return self


class MezmoCreateAccountConfig(_Input):
    """Create a child organization; may provision its owner and billing plan."""
    operation: Literal["create_account"] = "create_account"
    account: MezmoAccountFields = Field(..., description="Fields for the new child organization.")


class _Account(_Input):
    account_id: str = Field(..., min_length=1, max_length=24, description="Mezmo child account ID.")

    @field_validator("account_id")
    @classmethod
    def account_identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
            raise ValueError("Use a single Mezmo account ID")
        return value


class MezmoGetAccountConfig(_Account):
    """Retrieve one child account of your enterprise."""
    operation: Literal["get_account"] = "get_account"


class MezmoAttachAccountConfig(_Account):
    """Link an existing account to the enterprise, optionally changing its owner or plan."""
    operation: Literal["attach_account"] = "attach_account"
    plan: str | None = Field(None, min_length=4, max_length=50)
    owner: EmailStr | None = Field(None, title="New owner email")


class MezmoDetachAccountConfig(_Account):
    """Unlink a child account and downgrade it to trial, optionally deactivating it."""
    operation: Literal["detach_account"] = "detach_account"
    deactivate: StrictBool = Field(False, description="Also deactivate the account after detaching it.")


class MezmoBulkOperation(_Input):
    action: Literal["CREATE", "UPDATE", "DELETE"]
    operation_id: str | None = None
    entity_id: str | None = None
    entity: MezmoAccountFields | None = None

    @model_validator(mode="after")
    def action_fields(self):
        if self.action in {"UPDATE", "DELETE"} and not self.entity_id:
            raise ValueError("UPDATE and DELETE require entity_id")
        if self.action in {"CREATE", "UPDATE"} and self.entity is None:
            raise ValueError("CREATE and UPDATE require entity fields")
        if self.action == "CREATE" and self.entity_id is not None:
            raise ValueError("CREATE must omit entity_id")
        return self


class MezmoBulkAccountsConfig(_Input):
    """Create, update or delete up to 100 child accounts; inspect each returned outcome."""
    operation: Literal["bulk_account_operations"] = "bulk_account_operations"
    operations: list[MezmoBulkOperation] = Field(..., min_length=1, max_length=100)


class MezmoListPipelinesConfig(_Input):
    """List pipelines across all child organizations."""
    operation: Literal["list_pipelines"] = "list_pipelines"


class MezmoPipelineHealthConfig(_Input):
    """Read pipeline health across all child organizations, optionally including transform logs."""
    operation: Literal["get_pipeline_health"] = "get_pipeline_health"
    include_logs: StrictBool = True


class MezmoPipelineUsageConfig(_Input):
    """Read pipeline usage for a time window across child organizations."""
    operation: Literal["get_pipeline_usage"] = "get_pipeline_usage"
    from_time: str = Field(..., description="Beginning of the window as an RFC 3339 date-time with timezone.")
    to_time: str = Field(..., description="End of the window as an RFC 3339 date-time with timezone.")
    bucket: int = Field(..., description="Size of the interval represented by each returned metric result.")
    include_deleted: StrictBool = True
    pipeline_id: UUID | None = None
    traffic: Literal["ingress", "egress"] | None = None

    @field_validator("from_time", "to_time")
    @classmethod
    def timestamp(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if "T" not in value or parsed.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError("Use an RFC 3339 date-time including a timezone") from None
        return value

    @model_validator(mode="after")
    def ordered_window(self):
        if datetime.fromisoformat(self.to_time.replace("Z", "+00:00")) <= datetime.fromisoformat(self.from_time.replace("Z", "+00:00")):
            raise ValueError("End of window must be after its beginning")
        return self


class MezmoPipelineNodeSchemasConfig(_Input):
    """Get pipeline node types, operators and alert schemas."""
    operation: Literal["get_pipeline_node_schemas"] = "get_pipeline_node_schemas"


MezmoConfig = Annotated[Union[
    MezmoGetEnterpriseConfig, MezmoBulkAccountsConfig, MezmoCreateAccountConfig,
    MezmoGetAccountConfig, MezmoAttachAccountConfig, MezmoDetachAccountConfig,
    MezmoListPipelinesConfig, MezmoPipelineHealthConfig, MezmoPipelineUsageConfig,
    MezmoPipelineNodeSchemasConfig,
], Field(discriminator="operation")]


class MezmoNodeConfig(NodeConfig[MezmoConfig, MezmoAccessKeyCredential]):
    pass


def _redact(value, key):
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items() if k.lower() not in {"authorization", "access_key", "token"}}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value.replace(key, "[redacted]") if isinstance(value, str) else value


class MezmoNode(WorkflowNode):
    integration_type = "automation-mezmo"
    connection_evidence = ConnectionEvidence(noun="enterprise", identity_operation="get_enterprise")

    @classmethod
    def get_config_model(cls):
        return MezmoNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Mezmo access key")
        op = self.config.config
        key = self.config.credentials.access_key
        method, path = ROUTES[op.operation]
        headers = {"Authorization": "Token " + key, "Accept": "application/json"}
        params, body = {}, None
        if isinstance(op, _Account):
            path = path.replace("{account_id}", quote(op.account_id, safe=""))
        if isinstance(op, MezmoCreateAccountConfig):
            body = op.account.model_dump(mode="json", exclude_unset=True)
        elif isinstance(op, MezmoBulkAccountsConfig):
            body = {"operations": [item.model_dump(mode="json", exclude_none=True) for item in op.operations]}
            # Preserve explicitly supplied external_id=null when clearing an external reference.
            for raw, item in zip(body["operations"], op.operations):
                if item.entity is not None:
                    raw["entity"] = item.entity.model_dump(mode="json", exclude_unset=True)
            headers["Content-Type"] = "application/x-bulk+json"
        elif isinstance(op, MezmoAttachAccountConfig):
            body = op.model_dump(mode="json", exclude={"operation", "account_id"}, exclude_none=True)
        elif isinstance(op, MezmoDetachAccountConfig):
            params = {"deactivate": op.deactivate}
        elif isinstance(op, MezmoPipelineHealthConfig):
            params = {"include_logs": op.include_logs}
        elif isinstance(op, MezmoPipelineUsageConfig):
            params = op.model_dump(mode="json", exclude={"operation", "from_time", "to_time"}, exclude_none=True)
            params.update({"from": op.from_time, "to": op.to_time})
        kwargs = {"params": params, "headers": headers}
        if body is not None:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Mezmo request could not be completed") from None
        if not 200 <= response.status_code < 300:
            message = "Mezmo request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("message") or error.get("error") or error.get("errors") or message
            except ValueError:
                pass
            output = {"status": "error", "http_status": response.status_code, "error": _redact(str(message), key)}
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Expected a JSON response from Mezmo") from None
            if not isinstance(payload, dict) or not isinstance(payload.get("meta"), dict) or "data" not in payload or payload.get("errors") or payload.get("error"):
                raise ValueError("Mezmo response is missing its data and metadata envelope")
            expected = list if isinstance(op, (MezmoListPipelinesConfig, MezmoPipelineHealthConfig, MezmoPipelineUsageConfig)) else dict
            if not isinstance(payload["data"], expected):
                raise ValueError("Mezmo returned an unexpected data shape")
            output = {**_redact(payload, key), "status": "success"}
        await self.emit(output)
        return output

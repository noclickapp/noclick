"""Temporal Cloud Ops HTTP API v0.26.0.

Each operation maps to one published Cloud Ops operation. Mutations return the
provider's async operation; acceptance does not establish completed provisioning.
Contract: https://saas-api.tmprl.cloud/spec.json
Transport and version: https://docs.temporal.io/ops
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://saas-api.tmprl.cloud"
API_VERSION = "v0.26.0"


class TemporalAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Temporal API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://cloud.temporal.io/profile/api-keys",
            "x-credential-instructions": "Paste an existing Temporal Cloud user or service account API key. NoClick reads current identity to verify it. Cloud Ops permissions depend on the key owner's roles; provisioning and access management can require elevated permissions. This integration manages Cloud resources through saas-api.tmprl.cloud. Individual Workflow and Activity execution is outside the Cloud Ops API.",
        },
    )
    credential_type: Literal["temporal_api_key"] = Field(
        "temporal_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, populate_by_name=True
    )

    @field_validator(
        "namespace",
        "user_id",
        "service_account_id",
        "region",
        "async_operation_id",
        check_fields=False,
    )
    @classmethod
    def identifier(cls, value):
        if value is None:
            return value
        if (
            not value
            or value in {".", ".."}
            or value != value.strip()
            or any(c in value for c in "/\\?#")
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Use a single resource identifier without a path or URL")
        return value


class _Page(_Input):
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="Maximum items in this page; pass the returned nextPageToken to continue.",
    )
    page_token: str | None = Field(None, max_length=8192)


class AccountAccess(_Input):
    role: Literal[
        "ROLE_OWNER",
        "ROLE_ADMIN",
        "ROLE_DEVELOPER",
        "ROLE_FINANCE_ADMIN",
        "ROLE_READ",
        "ROLE_METRICS_READ",
    ] = Field(...)
    customRoles: list[str] | None = None

    @field_validator("role", mode="before")
    @classmethod
    def account_role(cls, value):
        # Accept the provider CLI's role spelling as well as the HTTP enum.
        if isinstance(value, str) and not value.startswith("ROLE_"):
            return "ROLE_" + value.upper().replace("-", "_")
        return value


class NamespaceAccess(_Input):
    permission: Literal[
        "PERMISSION_ADMIN", "PERMISSION_WRITE", "PERMISSION_READ"
    ] = Field(...)


class ProjectAccess(_Input):
    role: Literal[
        "PROJECT_ROLE_ADMIN",
        "PROJECT_ROLE_WRITE",
        "PROJECT_ROLE_READ",
        "PROJECT_ROLE_LIST",
        "PROJECT_ROLE_CONTRIBUTE",
        "PROJECT_ROLE_MEMBER",
    ] = Field(...)


class Access(_Input):
    accountAccess: AccountAccess = Field(...)
    namespaceAccesses: dict[str, NamespaceAccess] | None = None
    projectAccesses: dict[str, ProjectAccess] | None = None


class NamespaceScopedAccess(_Input):
    namespace: str = Field(..., min_length=1)
    access: NamespaceAccess = Field(...)


class ProjectScopedAccess(_Input):
    projectId: str = Field(..., min_length=1)
    access: ProjectAccess = Field(...)
    namespaceAccesses: dict[str, NamespaceAccess] | None = None


class UserSpec(_Input):
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
        description="Email address of the user. Creating a user may send an invitation.",
    )
    access: Access = Field(...)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Use a valid email address")
        return value


class ServiceAccountSpec(_Input):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    access: Access | None = None
    namespaceScopedAccess: NamespaceScopedAccess | None = None
    projectScopedAccess: ProjectScopedAccess | None = None

    @model_validator(mode="after")
    def one_access_type(self):
        if (
            sum(
                v is not None
                for v in (
                    self.access,
                    self.namespaceScopedAccess,
                    self.projectScopedAccess,
                )
            )
            != 1
        ):
            raise ValueError(
                "Provide exactly one account, namespace or project access specification"
            )
        return self


class ReplicaSpec(_Input):
    region: str = Field(
        ...,
        min_length=1,
        description="Region ID from List Regions, e.g. aws-us-west-2.",
    )


class ApiKeyAuth(_Input):
    enabled: bool = Field(True)


class NamespaceSpec(_Input):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Immutable namespace name without the account suffix.",
    )
    retentionDays: int = Field(..., ge=1, le=90)
    replicas: list[ReplicaSpec] = Field(..., min_length=1, max_length=2)
    apiKeyAuth: ApiKeyAuth = Field(default_factory=ApiKeyAuth)
    description: str | None = Field(None, max_length=255)
    searchAttributes: dict[
        str,
        Literal[
            "SEARCH_ATTRIBUTE_TYPE_TEXT",
            "SEARCH_ATTRIBUTE_TYPE_KEYWORD",
            "SEARCH_ATTRIBUTE_TYPE_INT",
            "SEARCH_ATTRIBUTE_TYPE_DOUBLE",
            "SEARCH_ATTRIBUTE_TYPE_BOOL",
            "SEARCH_ATTRIBUTE_TYPE_DATETIME",
            "SEARCH_ATTRIBUTE_TYPE_KEYWORD_LIST",
        ],
    ] | None = None


class GetAccountConfig(_Input):
    """Get Account"""

    operation: Literal["get_account"] = Field(
        "get_account", json_schema_extra={"ui:hidden": True}
    )


class GetCurrentIdentityConfig(_Input):
    """Get Current Identity"""

    operation: Literal["get_current_identity"] = Field(
        "get_current_identity", json_schema_extra={"ui:hidden": True}
    )


class GetAsyncOperationConfig(_Input):
    """Get Async Operation"""

    operation: Literal["get_async_operation"] = Field(
        "get_async_operation", json_schema_extra={"ui:hidden": True}
    )
    async_operation_id: str = Field(..., min_length=1)


class ListNamespacesConfig(_Page):
    """List Namespaces"""

    operation: Literal["list_namespaces"] = Field(
        "list_namespaces", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = None
    project_id: str | None = None


class GetNamespaceConfig(_Input):
    """Get Namespace"""

    operation: Literal["get_namespace"] = Field(
        "get_namespace", json_schema_extra={"ui:hidden": True}
    )
    namespace: str = Field(..., min_length=1)


class CreateNamespaceConfig(_Input):
    """Create Namespace"""

    operation: Literal["create_namespace"] = Field(
        "create_namespace", json_schema_extra={"ui:hidden": True}
    )
    spec: NamespaceSpec = Field(...)
    project_id: str | None = None
    tags: dict[str, str] | None = None
    async_operation_id: str | None = None


class DeleteNamespaceConfig(_Input):
    """Delete Namespace"""

    operation: Literal["delete_namespace"] = Field(
        "delete_namespace", json_schema_extra={"ui:hidden": True}
    )
    namespace: str = Field(
        ...,
        min_length=1,
        description="Permanently deletes the namespace and all its data.",
    )
    resource_version: str = Field(
        ...,
        min_length=1,
        description="Current resourceVersion from Get Namespace; guards against stale deletes.",
    )
    async_operation_id: str | None = None


class ListUsersConfig(_Page):
    """List Users"""

    operation: Literal["list_users"] = Field(
        "list_users", json_schema_extra={"ui:hidden": True}
    )
    email: str | None = None
    namespace: str | None = None


class GetUserConfig(_Input):
    """Get User"""

    operation: Literal["get_user"] = Field(
        "get_user", json_schema_extra={"ui:hidden": True}
    )
    user_id: str = Field(..., min_length=1)


class CreateUserConfig(_Input):
    """Create User"""

    operation: Literal["create_user"] = Field(
        "create_user", json_schema_extra={"ui:hidden": True}
    )
    spec: UserSpec = Field(...)
    async_operation_id: str | None = None


class UpdateUserConfig(_Input):
    """Update User"""

    operation: Literal["update_user"] = Field(
        "update_user", json_schema_extra={"ui:hidden": True}
    )
    user_id: str = Field(..., min_length=1)
    spec: UserSpec = Field(
        ...,
        description="Complete replacement specification; retain all desired access assignments from the current resource.",
    )
    resource_version: str = Field(
        ..., min_length=1, description="Current resourceVersion from the get operation."
    )
    async_operation_id: str | None = None


class DeleteUserConfig(_Input):
    """Delete User"""

    operation: Literal["delete_user"] = Field(
        "delete_user", json_schema_extra={"ui:hidden": True}
    )
    user_id: str = Field(..., min_length=1)
    resource_version: str = Field(..., min_length=1)
    async_operation_id: str | None = None


class ListServiceAccountsConfig(_Page):
    """List Service Accounts"""

    operation: Literal["list_service_accounts"] = Field(
        "list_service_accounts", json_schema_extra={"ui:hidden": True}
    )


class GetServiceAccountConfig(_Input):
    """Get Service Account"""

    operation: Literal["get_service_account"] = Field(
        "get_service_account", json_schema_extra={"ui:hidden": True}
    )
    service_account_id: str = Field(..., min_length=1)


class CreateServiceAccountConfig(_Input):
    """Create Service Account"""

    operation: Literal["create_service_account"] = Field(
        "create_service_account", json_schema_extra={"ui:hidden": True}
    )
    spec: ServiceAccountSpec = Field(...)
    async_operation_id: str | None = None


class UpdateServiceAccountConfig(_Input):
    """Update Service Account"""

    operation: Literal["update_service_account"] = Field(
        "update_service_account", json_schema_extra={"ui:hidden": True}
    )
    service_account_id: str = Field(..., min_length=1)
    spec: ServiceAccountSpec = Field(
        ...,
        description="Complete replacement specification; retain all desired access assignments from the current resource.",
    )
    resource_version: str = Field(
        ..., min_length=1, description="Current resourceVersion from the get operation."
    )
    async_operation_id: str | None = None


class DeleteServiceAccountConfig(_Input):
    """Delete Service Account"""

    operation: Literal["delete_service_account"] = Field(
        "delete_service_account", json_schema_extra={"ui:hidden": True}
    )
    service_account_id: str = Field(..., min_length=1)
    resource_version: str = Field(..., min_length=1)
    async_operation_id: str | None = None


class ListRegionsConfig(_Input):
    """List Regions"""

    operation: Literal["list_regions"] = Field(
        "list_regions", json_schema_extra={"ui:hidden": True}
    )


class GetRegionConfig(_Input):
    """Get Region"""

    operation: Literal["get_region"] = Field(
        "get_region", json_schema_extra={"ui:hidden": True}
    )
    region: str = Field(..., min_length=1)


class ListApiKeysConfig(_Page):
    """List Api Keys"""

    operation: Literal["list_api_keys"] = Field(
        "list_api_keys", json_schema_extra={"ui:hidden": True}
    )
    owner_id: str | None = None
    owner_type: Literal["OWNER_TYPE_USER", "OWNER_TYPE_SERVICE_ACCOUNT"] | None = None


class OnNewAuditLogConfig(PollTriggerConfigBase):
    """New Temporal Cloud audit log. Requires Account Owner or Global Administrator.

    Baselines existing logs when armed. Monitors control plane activity (namespace,
    user and access changes), not Workflow or Activity execution events.
    """

    operation: Literal["on_new_audit_log"] = Field(
        "on_new_audit_log",
        json_schema_extra={
            "ui:hidden": True,
            "x-is-trigger": True,
            "x-category": "Triggers",
            "x-display-name": "New Audit Log",
        },
    )
    lookback_minutes: int = Field(
        60,
        ge=1,
        le=43200,
        title="Lookback (minutes)",
        description="Recheck this rolling time window for delayed logs; choose a window longer than the polling interval and expected downtime. Temporal retains 30 days. At most 10,000 logs may be in the window.",
    )
    operation_filter: str | None = Field(
        None,
        min_length=1,
        title="Operation filter",
        description="Optional exact audit operation, e.g. CreateNamespace or UserLogin. Leave empty for all operations. Filtering happens after fetching all pages.",
    )


TemporalConfig = Annotated[
    Union[
        OnNewAuditLogConfig,
        GetAccountConfig,
        GetCurrentIdentityConfig,
        GetAsyncOperationConfig,
        ListNamespacesConfig,
        GetNamespaceConfig,
        CreateNamespaceConfig,
        DeleteNamespaceConfig,
        ListUsersConfig,
        GetUserConfig,
        CreateUserConfig,
        UpdateUserConfig,
        DeleteUserConfig,
        ListServiceAccountsConfig,
        GetServiceAccountConfig,
        CreateServiceAccountConfig,
        UpdateServiceAccountConfig,
        DeleteServiceAccountConfig,
        ListRegionsConfig,
        GetRegionConfig,
        ListApiKeysConfig,
    ],
    Field(discriminator="operation"),
]


class TemporalFullConfig(NodeConfig[TemporalConfig, TemporalAPIKeyCredential]):
    pass


ROUTES = {
    "on_new_audit_log": {
        "method": "GET",
        "path": "/cloud/audit-logs",
        "query": {
            "page_size": "pageSize",
            "page_token": "pageToken",
            "start_time": "startTimeInclusive",
            "end_time": "endTimeExclusive",
        },
        "body": {},
    },
    "get_account": {"method": "GET", "path": "/cloud/account", "query": {}, "body": {}},
    "get_current_identity": {
        "method": "GET",
        "path": "/cloud/current-identity",
        "query": {},
        "body": {},
    },
    "get_async_operation": {
        "method": "GET",
        "path": "/cloud/operations/{async_operation_id}",
        "query": {},
        "body": {},
    },
    "list_namespaces": {
        "method": "GET",
        "path": "/cloud/namespaces",
        "query": {
            "page_size": "pageSize",
            "page_token": "pageToken",
            "name": "name",
            "project_id": "projectId",
        },
        "body": {},
    },
    "get_namespace": {
        "method": "GET",
        "path": "/cloud/namespaces/{namespace}",
        "query": {},
        "body": {},
    },
    "create_namespace": {
        "method": "POST",
        "path": "/cloud/namespaces",
        "query": {},
        "body": {
            "spec": "spec",
            "project_id": "projectId",
            "tags": "tags",
            "async_operation_id": "asyncOperationId",
        },
    },
    "delete_namespace": {
        "method": "DELETE",
        "path": "/cloud/namespaces/{namespace}",
        "query": {
            "resource_version": "resourceVersion",
            "async_operation_id": "asyncOperationId",
        },
        "body": {},
    },
    "list_users": {
        "method": "GET",
        "path": "/cloud/users",
        "query": {
            "page_size": "pageSize",
            "page_token": "pageToken",
            "email": "email",
            "namespace": "namespace",
        },
        "body": {},
    },
    "get_user": {
        "method": "GET",
        "path": "/cloud/users/{user_id}",
        "query": {},
        "body": {},
    },
    "create_user": {
        "method": "POST",
        "path": "/cloud/users",
        "query": {},
        "body": {"spec": "spec", "async_operation_id": "asyncOperationId"},
    },
    "update_user": {
        "method": "POST",
        "path": "/cloud/users/{user_id}",
        "query": {},
        "body": {
            "spec": "spec",
            "resource_version": "resourceVersion",
            "async_operation_id": "asyncOperationId",
        },
    },
    "delete_user": {
        "method": "DELETE",
        "path": "/cloud/users/{user_id}",
        "query": {
            "resource_version": "resourceVersion",
            "async_operation_id": "asyncOperationId",
        },
        "body": {},
    },
    "list_service_accounts": {
        "method": "GET",
        "path": "/cloud/service-accounts",
        "query": {"page_size": "pageSize", "page_token": "pageToken"},
        "body": {},
    },
    "get_service_account": {
        "method": "GET",
        "path": "/cloud/service-accounts/{service_account_id}",
        "query": {},
        "body": {},
    },
    "create_service_account": {
        "method": "POST",
        "path": "/cloud/service-accounts",
        "query": {},
        "body": {"spec": "spec", "async_operation_id": "asyncOperationId"},
    },
    "update_service_account": {
        "method": "POST",
        "path": "/cloud/service-accounts/{service_account_id}",
        "query": {},
        "body": {
            "spec": "spec",
            "resource_version": "resourceVersion",
            "async_operation_id": "asyncOperationId",
        },
    },
    "delete_service_account": {
        "method": "DELETE",
        "path": "/cloud/service-accounts/{service_account_id}",
        "query": {
            "resource_version": "resourceVersion",
            "async_operation_id": "asyncOperationId",
        },
        "body": {},
    },
    "list_regions": {
        "method": "GET",
        "path": "/cloud/regions",
        "query": {},
        "body": {},
    },
    "get_region": {
        "method": "GET",
        "path": "/cloud/regions/{region}",
        "query": {},
        "body": {},
    },
    "list_api_keys": {
        "method": "GET",
        "path": "/cloud/api-keys",
        "query": {
            "page_size": "pageSize",
            "page_token": "pageToken",
            "owner_id": "ownerId",
            "owner_type": "ownerType",
        },
        "body": {},
    },
}


LIST_KEYS = {
    "list_namespaces": "namespaces",
    "list_users": "users",
    "list_service_accounts": "serviceAccount",
    "list_regions": "regions",
    "list_api_keys": "apiKeys",
}
DETAIL_KEYS = {
    "get_account": "account",
    "get_namespace": "namespace",
    "get_user": "user",
    "get_service_account": "serviceAccount",
    "get_region": "region",
    "get_async_operation": "asyncOperation",
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class TemporalNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-temporal"
    connection_evidence = ConnectionEvidence(
        operation="get_current_identity", noun="Temporal Cloud identity"
    )

    @classmethod
    def get_config_model(cls):
        return TemporalFullConfig

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "audit_logs" not in output:
            return super().resolve_agent_event(output)
        logs = output["audit_logs"]
        if not logs:
            return None
        lines = [
            "Temporal Cloud: new control plane audit activity.",
            "OK records API acceptance; it does not establish completed provisioning.",
        ]
        for log in logs[:10]:
            principal = log.get("principal") or {}
            who = principal.get("name") or principal.get("id") or "Unknown principal"
            lines.append(
                f"- {who}: {log.get('operation') or 'Audit operation'} "
                f"(status {log.get('status') or 'unspecified'}, log {log['logId']}). "
                f"Recorded: {json.dumps(log.get('emitTime'))}. "
                f"Principal: {json.dumps(principal)}. "
                f"Request/async operation ID: {log.get('asyncOperationId') or 'none'}. "
                f"Details: {json.dumps(log.get('rawDetails') or {}, ensure_ascii=False)}"
            )
        if len(logs) > 10:
            lines.append(f"And {len(logs) - 10} more logs in the trigger output.")
        return {
            "text": "\n".join(lines),
            "conversation_key": None,
            "title": "Temporal Cloud audit activity",
        }

    async def _poll_audit_logs(self, config, credential):
        # Fix both bounds across pages so newly arriving records cannot move the window.
        end = datetime.now(timezone.utc)
        values = {
            "page_size": 500,
            "start_time": (
                end - timedelta(minutes=config.lookback_minutes)
            ).isoformat(),
            "end_time": end.isoformat(),
        }
        logs = []
        tokens = set()
        for _ in range(20):
            data = await self._request(ROUTES[config.operation], values, credential)
            rows, token = data.get("logs", []), data.get("nextPageToken", "")
            if (
                not isinstance(rows, list)
                or not isinstance(token, str)
                or any(
                    not isinstance(row, dict)
                    or not isinstance(row.get("logId"), str)
                    or not row["logId"]
                    for row in rows
                )
            ):
                raise ValueError("Temporal returned an invalid audit log page")
            logs.extend(rows)
            if len(logs) > 10000:
                raise ValueError(
                    "Temporal audit window exceeds 10,000 logs; shorten the lookback"
                )
            if not token:
                break
            if token in tokens:
                raise ValueError("Temporal repeated an audit log page token")
            tokens.add(token)
            values["page_token"] = token
        else:
            raise ValueError(
                "Temporal audit window exceeds 20 pages; shorten the lookback"
            )
        selected = [
            row
            for row in logs
            if not config.operation_filter
            or row.get("operation") == config.operation_filter
        ]
        fresh = await self._filter_unseen(selected, lambda row: row["logId"])
        fresh = _redact(fresh, credential.api_key)
        return {"status": "success", "audit_logs": fresh, "new_log_count": len(fresh)}

    async def _request(self, route, values, credential):
        path = route["path"]
        for field in re.findall(r"{([^}]+)}", path):
            path = path.replace("{" + field + "}", quote(values[field], safe=""))
        params = {
            wire: values[field]
            for field, wire in route["query"].items()
            if field in values
        }
        body = {
            wire: values[field]
            for field, wire in route["body"].items()
            if field in values
        }
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    route["method"],
                    BASE + path,
                    headers={
                        "Authorization": "Bearer " + credential.api_key,
                        "Accept": "application/json",
                        "temporal-cloud-api-version": API_VERSION,
                    },
                    params=params,
                    **({"json": body} if route["body"] else {}),
                )
        except httpx.HTTPError:
            raise ValueError(
                "Temporal request did not complete; inspect resource and async operation status before retrying a mutation"
            ) from None
        if response.status_code != 200:
            raise ValueError(
                f"Temporal HTTP {response.status_code}: {_redact(response.text[:2000], credential.api_key)}"
            )
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Temporal returned a non-JSON response") from None
        if (
            not isinstance(data, dict)
            or data.get("code")
            or data.get("error")
            or data.get("errors")
        ):
            raise ValueError("Temporal returned an invalid response or error envelope")
        return data

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Temporal API key")
        if isinstance(config, OnNewAuditLogConfig):
            return await self._poll_audit_logs(config, credential)
        data = await self._request(
            ROUTES[config.operation], config.model_dump(exclude_none=True), credential
        )
        result = {"status": "success", "data": _redact(data, credential.api_key)}
        if config.operation in LIST_KEYS:
            # Protobuf JSON omits empty repeated fields. An absent array is a valid empty page.
            items = data.get(LIST_KEYS[config.operation], [])
            token = data.get("nextPageToken", "")
            if (
                not isinstance(items, list)
                or any(not isinstance(row, dict) for row in items)
                or not isinstance(token, str)
            ):
                raise ValueError("Temporal returned an invalid page")
            result.update(
                items=_redact(items, credential.api_key),
                next_page_token=token or None,
                has_more=bool(token),
            )
        elif config.operation in DETAIL_KEYS:
            if not isinstance(data.get(DETAIL_KEYS[config.operation]), dict):
                raise ValueError("Temporal returned an incomplete resource")
        elif config.operation == "get_current_identity":
            identities = [
                data[key]
                for key in ("user", "serviceAccount")
                if isinstance(data.get(key), dict)
            ]
            if not identities or not any(row.get("id") for row in identities):
                raise ValueError("Temporal returned no authenticated identity")
            result["items"] = [
                {
                    "id": row["id"],
                    "name": row.get("spec", {}).get("email")
                    or row.get("spec", {}).get("name")
                    or row["id"],
                }
                for row in identities
                if row.get("id")
            ]
        else:
            # Cloud Ops writes are asynchronous. Never claim the resource is ready or deleted.
            if not isinstance(data.get("asyncOperation"), dict) or not data[
                "asyncOperation"
            ].get("id"):
                raise ValueError(
                    "Temporal returned no mutation operation; inspect resource state before retrying"
                )
            result["async_operation"] = _redact(
                data["asyncOperation"], credential.api_key
            )
        return _redact(result, credential.api_key)

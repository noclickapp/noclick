"""TrackVia OpenAPI 1.0.0 operations.

Contract: https://developer.trackvia.com/openapi.yaml
Authentication: /getting-started-with-the-api/api-keys/ and /tokens/.
Each operation performs exactly one API request. Pagination is explicit.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import re
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class TrackViaTokenCredential(BaseModel):
    model_config = ConfigDict(title="TrackVia API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.trackvia.com/getting-started-with-the-api/tokens/",
            "x-credential-instructions": "In TrackVia Account Settings → API Access, copy your account API key and an active API user's auth token. Paste them below. Tokens expire on the date chosen by your administrator; replace expired tokens here. If needed, enter the account ID and your custom TrackVia tenant URL.",
        })
    credential_type: Literal["trackvia_api_token"] = Field("trackvia_api_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Auth Token", repr=False, json_schema_extra={"ui:widget": "password"})
    user_key: str = Field(..., title="Account API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    account_id: str | None = Field(None, title="Account ID", description="Optional account-id header for an account selection.")
    api_base_url: str = Field("https://go.trackvia.com", title="TrackVia Tenant URL", description="HTTPS URL of your TrackVia tenant, without /openapi.")

    @field_validator("access_token", "user_key", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the credential without a header prefix or whitespace")
        return value

    @field_validator("api_base_url", mode="before")
    @classmethod
    def tenant(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter an HTTPS TrackVia tenant URL")
        value = value.strip().rstrip("/").lower()
        if not re.fullmatch(r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trackvia\.com", value):
            raise ValueError("Use https://go.trackvia.com or your custom TrackVia subdomain")
        return value

    @field_validator("account_id")
    @classmethod
    def account(cls, value):
        if value is not None and not re.fullmatch(r"[0-9]+", value):
            raise ValueError("Enter the numeric TrackVia account ID")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("data", "body", "attachment_ids", mode="before", check_fields=False)
    @classmethod
    def json_input(cls, value):
        # Config forms store JSON text; agent tools can supply native objects.
        return json.loads(value) if isinstance(value, str) else value

    @field_validator("field_name", check_fields=False)
    @classmethod
    def field_segment(cls, value):
        if value in {".", ".."}:
            raise ValueError("Enter a field name, not a path segment")
        return value


class TrackViaListUsersConfig(_Input):
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})
    start: int = Field(0, ge=0, title="Start Offset", description="Zero-based offset. Increase by max for the next page.")
    max: int = Field(100, ge=1, le=100000, title="Page Size")


class TrackViaCreateUserConfig(_Input):
    operation: Literal["create_user"] = Field("create_user", title="Create User", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title="Email", json_schema_extra={"format": "email"})
    first_name: str = Field(..., min_length=1, title="First Name")
    last_name: str = Field(..., min_length=1, title="Last Name")
    time_zone: str | None = Field(None, title="Time Zone")


class TrackViaListAppsConfig(_Input):
    operation: Literal["list_apps"] = Field("list_apps", title="List Applications", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, title="Name", description="Optional application or view name filter.")


class TrackViaListViewsConfig(_Input):
    operation: Literal["list_views"] = Field("list_views", title="List Views", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, title="Name", description="Optional application or view name filter.")


class TrackViaListRecordsConfig(_Input):
    operation: Literal["list_records"] = Field("list_records", title="List Records", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    start: int = Field(0, ge=0, title="Start Offset", description="Zero-based offset. Increase by max for the next page.")
    max: int = Field(100, ge=1, le=100000, title="Page Size")


class TrackViaSearchRecordsConfig(_Input):
    operation: Literal["search_records"] = Field("search_records", title="Search Records", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    q: str | None = Field(None, title="Search Text")
    start: int = Field(0, ge=0, title="Start Offset", description="Zero-based offset. Increase by max for the next page.")
    max: int = Field(100, ge=1, le=100000, title="Page Size")


class TrackViaListMicroservicesConfig(_Input):
    operation: Literal["list_microservices"] = Field("list_microservices", title="List Microservices", json_schema_extra={"ui:hidden": True})


class TrackViaInvokeMicroserviceQueryConfig(_Input):
    operation: Literal["invoke_microservice_query"] = Field("invoke_microservice_query", title="Invoke Microservice With Query", json_schema_extra={"ui:hidden": True})
    microservice_id: int = Field(..., ge=1, title="Microservice ID")
    param: str | None = Field(None, title="Microservice Query Value", description="Sent as the documented param query parameter.")


class TrackViaInvokeMicroserviceConfig(_Input):
    operation: Literal["invoke_microservice"] = Field("invoke_microservice", title="Invoke Microservice", json_schema_extra={"ui:hidden": True})
    microservice_id: int = Field(..., ge=1, title="Microservice ID")
    body: dict[str, Any] = Field(..., title="Microservice Body", description="JSON object expected by this microservice.", json_schema_extra={"ui:widget": "textarea"})


class TrackViaCreateRecordConfig(_Input):
    operation: Literal["create_record"] = Field("create_record", title="Create Record", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    data: list[dict[str, Any]] = Field(..., min_length=1, max_length=1, title="Record Fields", description='One object of field names and values, e.g. [{"Field A": "Some Text", "Field B": 12345}].', json_schema_extra={"ui:widget": "textarea"})


class TrackViaGetRecordConfig(_Input):
    operation: Literal["get_record"] = Field("get_record", title="Get Record", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    record_id: int = Field(..., ge=1, title="Record ID")


class TrackViaUpdateRecordConfig(_Input):
    operation: Literal["update_record"] = Field("update_record", title="Update Record", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    record_id: int = Field(..., ge=1, title="Record ID")
    data: list[dict[str, Any]] = Field(..., min_length=1, max_length=1, title="Record Fields", description='One object of field names and values, e.g. [{"Field A": "Some Text", "Field B": 12345}].', json_schema_extra={"ui:widget": "textarea"})


class TrackViaDeleteRecordConfig(_Input):
    operation: Literal["delete_record"] = Field("delete_record", title="Delete Record", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    record_id: int = Field(..., ge=1, title="Record ID")


class TrackViaDeleteFileConfig(_Input):
    operation: Literal["delete_file"] = Field("delete_file", title="Delete Record File", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    record_id: int = Field(..., ge=1, title="Record ID")
    field_name: str = Field(..., min_length=1, title="Field Name")


class TrackViaDeleteAttachmentsConfig(_Input):
    operation: Literal["delete_attachments"] = Field("delete_attachments", title="Delete Selected Attachments", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    record_id: int = Field(..., ge=1, title="Record ID")
    field_name: str = Field(..., min_length=1, title="Field Name")
    attachment_ids: list[int] = Field(..., min_length=1, title="Attachment IDs", description="JSON array of attachment IDs to delete from the selected field.", json_schema_extra={"ui:widget": "textarea"})


class TrackViaDeleteAllAttachmentsConfig(_Input):
    operation: Literal["delete_all_attachments"] = Field("delete_all_attachments", title="Delete All Field Attachments", json_schema_extra={"ui:hidden": True})
    view_id: int = Field(..., ge=1, title="View ID")
    record_id: int = Field(..., ge=1, title="Record ID")
    field_name: str = Field(..., min_length=1, title="Field Name")


TrackViaConfig = Annotated[
    Union[
        TrackViaListUsersConfig,
        TrackViaCreateUserConfig,
        TrackViaListAppsConfig,
        TrackViaListViewsConfig,
        TrackViaListRecordsConfig,
        TrackViaSearchRecordsConfig,
        TrackViaListMicroservicesConfig,
        TrackViaInvokeMicroserviceQueryConfig,
        TrackViaInvokeMicroserviceConfig,
        TrackViaCreateRecordConfig,
        TrackViaGetRecordConfig,
        TrackViaUpdateRecordConfig,
        TrackViaDeleteRecordConfig,
        TrackViaDeleteFileConfig,
        TrackViaDeleteAttachmentsConfig,
        TrackViaDeleteAllAttachmentsConfig,
    ],
    Field(discriminator="operation"),
]


class TrackViaFullConfig(NodeConfig[TrackViaConfig, TrackViaTokenCredential]):
    pass


OPERATIONS = {'list_users': ('GET', '/users'),
 'create_user': ('POST', '/users'),
 'list_apps': ('GET', '/apps'),
 'list_views': ('GET', '/views'),
 'list_records': ('GET', '/views/{view_id}'),
 'search_records': ('GET', '/views/{view_id}/find'),
 'list_microservices': ('GET', '/integrations'),
 'invoke_microservice_query': ('GET', '/integrations/{microservice_id}/invoke'),
 'invoke_microservice': ('POST', '/integrations/{microservice_id}/invoke'),
 'create_record': ('POST', '/views/{view_id}/records'),
 'get_record': ('GET', '/views/{view_id}/records/{record_id}'),
 'update_record': ('PUT', '/views/{view_id}/records/{record_id}'),
 'delete_record': ('DELETE', '/views/{view_id}/records/{record_id}'),
 'delete_file': ('DELETE', '/views/{view_id}/records/{record_id}/files/{field_name}'),
 'delete_attachments': ('DELETE', '/views/{view_id}/records/{record_id}/attachments/{field_name}'),
 'delete_all_attachments': ('DELETE', '/views/{view_id}/records/{record_id}/attachments/{field_name}/all')}


class TrackViaNode(WorkflowNode):
    integration_type = "automation-trackvia"
    connection_evidence = ConnectionEvidence(noun="TrackVia applications", operation="list_apps")

    @classmethod
    def get_config_model(cls):
        return TrackViaFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a TrackVia API token")
        cred = self.config.credentials
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        method, path = OPERATIONS[config.operation]
        for key in ("view_id", "record_id", "microservice_id", "field_name"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        values.pop("operation")
        headers = {"Authorization": "Bearer " + cred.access_token, "Accept": "application/json"}
        if cred.account_id:
            headers["account-id"] = cred.account_id
        query = {"user_key": cred.user_key}
        kwargs = {}
        if config.operation == "create_user":
            kwargs["data"] = {{"first_name": "firstName", "last_name": "lastName", "time_zone": "timeZone"}.get(k, k): v for k, v in values.items()}
        elif config.operation in {"create_record", "update_record"}:
            kwargs["json"] = {"data": values["data"]}
        elif config.operation == "invoke_microservice":
            kwargs["json"] = values["body"]
        else:
            query.update({("attachmentIds" if k == "attachment_ids" else k): v for k, v in values.items()})
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, cred.api_base_url + "/openapi" + path,
                                            headers=headers, params=query, **kwargs)
        if response.status_code >= 300:
            # Preserve provider rejection text for the shared connect verdict,
            # without leaking a provider-echoed secret or a query-bearing URL.
            message = "TrackVia rejected this request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except ValueError:
                pass
            for secret in (cred.access_token, cred.user_key):
                message = message.replace(secret, "[redacted]")
            return {"status": "error", "error": message, "http_status": response.status_code}
        if response.status_code == 204 or not response.content:
            return {"status": "success", "data": None}
        body = response.json()
        if isinstance(body, dict) and body.get("errors"):
            return {"status": "error", "error": "TrackVia returned errors", "data": body}
        return {"status": "success", "data": body}

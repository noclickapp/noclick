"""HaloPSA v2 fixed REST operations using a manually supplied bearer token.

Contract: https://haloacademy.halopsa.com/api/swagger/v2/swagger.json
Token instructions: https://halopsa.com/guides/article/?kbid=1499
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class HalopsaAccessTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="HaloPSA Access Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://halopsa.com/guides/article/?kbid=1499",
            "x-credential-instructions": "Paste an existing HaloPSA API access token and your hosted instance URL. Obtain a token using your Halo API application's configured authentication flow. Grant permissions for the operations you use. Tokens expire; replace the token when it expires. This connection does not refresh tokens. Hosted halopsa.com instances are supported.",
        },
    )
    credential_type: Literal["halopsa_access_token"] = Field(
        "halopsa_access_token", json_schema_extra={"ui:hidden": True}
    )
    instance_url: str = Field(
        ...,
        title="Instance URL",
        description="For example https://yourcompany.halopsa.com",
    )
    access_token: str = Field(
        ...,
        title="Access token",
        min_length=1,
        max_length=8192,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("instance_url")
    @classmethod
    def instance(cls, value):
        import re

        value = value.strip().rstrip("/")
        p = urlsplit(value)
        if (
            p.scheme != "https"
            or not re.fullmatch(
                r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.halopsa\.com", p.netloc
            )
            or p.path
            or p.query
            or p.fragment
        ):
            raise ValueError(
                "Use your hosted https://yourcompany.halopsa.com instance URL"
            )
        return "https://" + p.netloc.lower()

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page_no: int = Field(1, ge=1, le=1000000)
    page_size: int = Field(50, ge=1, le=100)
    search: str | None = Field(None, max_length=500)


class _Update(_Input):
    id: int = Field(..., ge=1, le=2147483647, title="Record ID")

    @model_validator(mode="after")
    def changed(self):
        if not any(
            v is not None
            for k, v in self.model_dump().items()
            if k not in {"operation", "id"}
        ):
            raise ValueError("Supply at least one field to update")
        return self


class HalopsaListTicketConfig(_Page):
    operation: Literal["list_tickets"] = Field(
        "list_tickets", json_schema_extra={"ui:hidden": True}
    )


class HalopsaGetTicketConfig(_Input):
    operation: Literal["get_ticket"] = Field(
        "get_ticket", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., ge=1, le=2147483647, title="Record ID")


class HalopsaCreateTicketConfig(_Input):
    operation: Literal["create_ticket"] = Field(
        "create_ticket", json_schema_extra={"ui:hidden": True}
    )
    summary: str = Field(..., min_length=1, max_length=20000)
    details: str | None = Field(None, min_length=1, max_length=20000)
    client_id: int | None = Field(None, ge=1, le=2147483647)
    site_id: int | None = Field(None, ge=1, le=2147483647)
    user_id: int | None = Field(None, ge=1, le=2147483647)
    status_id: int | None = Field(None, ge=1, le=2147483647)
    priority_id: int | None = Field(None, ge=1, le=2147483647)
    tickettype_id: int | None = Field(None, ge=1, le=2147483647)
    agent_id: int | None = Field(None, ge=1, le=2147483647)


class HalopsaUpdateTicketConfig(_Update):
    operation: Literal["update_ticket"] = Field(
        "update_ticket", json_schema_extra={"ui:hidden": True}
    )
    summary: str | None = Field(None, min_length=1, max_length=20000)
    details: str | None = Field(None, min_length=1, max_length=20000)
    client_id: int | None = Field(None, ge=1, le=2147483647)
    site_id: int | None = Field(None, ge=1, le=2147483647)
    user_id: int | None = Field(None, ge=1, le=2147483647)
    status_id: int | None = Field(None, ge=1, le=2147483647)
    priority_id: int | None = Field(None, ge=1, le=2147483647)
    tickettype_id: int | None = Field(None, ge=1, le=2147483647)
    agent_id: int | None = Field(None, ge=1, le=2147483647)


class HalopsaListClientConfig(_Page):
    operation: Literal["list_clients"] = Field(
        "list_clients", json_schema_extra={"ui:hidden": True}
    )


class HalopsaGetClientConfig(_Input):
    operation: Literal["get_client"] = Field(
        "get_client", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., ge=1, le=2147483647, title="Record ID")


class HalopsaCreateClientConfig(_Input):
    operation: Literal["create_client"] = Field(
        "create_client", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=20000)


class HalopsaUpdateClientConfig(_Update):
    operation: Literal["update_client"] = Field(
        "update_client", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = Field(None, min_length=1, max_length=20000)


class HalopsaListUserConfig(_Page):
    operation: Literal["list_users"] = Field(
        "list_users", json_schema_extra={"ui:hidden": True}
    )


class HalopsaGetUserConfig(_Input):
    operation: Literal["get_user"] = Field(
        "get_user", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., ge=1, le=2147483647, title="Record ID")


class HalopsaCreateUserConfig(_Input):
    operation: Literal["create_user"] = Field(
        "create_user", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=20000)
    emailaddress: str | None = Field(None, min_length=1, max_length=20000)
    site_id: int = Field(..., ge=1, le=2147483647)


class HalopsaUpdateUserConfig(_Update):
    operation: Literal["update_user"] = Field(
        "update_user", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = Field(None, min_length=1, max_length=20000)
    emailaddress: str | None = Field(None, min_length=1, max_length=20000)
    site_id: int | None = Field(None, ge=1, le=2147483647)


class HalopsaListSiteConfig(_Page):
    operation: Literal["list_sites"] = Field(
        "list_sites", json_schema_extra={"ui:hidden": True}
    )


class HalopsaGetSiteConfig(_Input):
    operation: Literal["get_site"] = Field(
        "get_site", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., ge=1, le=2147483647, title="Record ID")


class HalopsaCreateSiteConfig(_Input):
    operation: Literal["create_site"] = Field(
        "create_site", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=20000)
    client_id: int = Field(..., ge=1, le=2147483647)


class HalopsaUpdateSiteConfig(_Update):
    operation: Literal["update_site"] = Field(
        "update_site", json_schema_extra={"ui:hidden": True}
    )
    name: str | None = Field(None, min_length=1, max_length=20000)
    client_id: int | None = Field(None, ge=1, le=2147483647)


class HalopsaListActionsConfig(_Input):
    operation: Literal["list_actions"] = Field(
        "list_actions", json_schema_extra={"ui:hidden": True}
    )
    ticket_id: int = Field(..., ge=1, le=2147483647)


class HalopsaGetActionConfig(_Input):
    operation: Literal["get_action"] = Field(
        "get_action", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., ge=1, le=2147483647)
    ticket_id: int = Field(..., ge=1, le=2147483647)


class HalopsaCreateActionConfig(_Input):
    operation: Literal["create_action"] = Field(
        "create_action", json_schema_extra={"ui:hidden": True}
    )
    ticket_id: int = Field(..., ge=1, le=2147483647)
    note: str = Field(..., min_length=1, max_length=20000)
    outcome: str | None = Field(None, max_length=500)
    timetaken: float | None = Field(None, ge=0, le=100000)


HalopsaConfig = Annotated[
    Union[
        HalopsaListTicketConfig,
        HalopsaGetTicketConfig,
        HalopsaCreateTicketConfig,
        HalopsaUpdateTicketConfig,
        HalopsaListClientConfig,
        HalopsaGetClientConfig,
        HalopsaCreateClientConfig,
        HalopsaUpdateClientConfig,
        HalopsaListUserConfig,
        HalopsaGetUserConfig,
        HalopsaCreateUserConfig,
        HalopsaUpdateUserConfig,
        HalopsaListSiteConfig,
        HalopsaGetSiteConfig,
        HalopsaCreateSiteConfig,
        HalopsaUpdateSiteConfig,
        HalopsaListActionsConfig,
        HalopsaGetActionConfig,
        HalopsaCreateActionConfig,
    ],
    Field(discriminator="operation"),
]


class HalopsaFullConfig(NodeConfig[HalopsaConfig, HalopsaAccessTokenCredential]):
    pass


ROUTES = {
    "list_tickets": ("GET", "/Tickets", "tickets", "list"),
    "get_ticket": ("GET", "/Tickets", "tickets", "get"),
    "create_ticket": ("POST", "/Tickets", "tickets", "create"),
    "update_ticket": ("POST", "/Tickets", "tickets", "update"),
    "list_clients": ("GET", "/Client", "clients", "list"),
    "get_client": ("GET", "/Client", "clients", "get"),
    "create_client": ("POST", "/Client", "clients", "create"),
    "update_client": ("POST", "/Client", "clients", "update"),
    "list_users": ("GET", "/Users", "users", "list"),
    "get_user": ("GET", "/Users", "users", "get"),
    "create_user": ("POST", "/Users", "users", "create"),
    "update_user": ("POST", "/Users", "users", "update"),
    "list_sites": ("GET", "/Site", "sites", "list"),
    "get_site": ("GET", "/Site", "sites", "get"),
    "create_site": ("POST", "/Site", "sites", "create"),
    "update_site": ("POST", "/Site", "sites", "update"),
    "list_actions": ("GET", "/Actions", "actions", "list"),
    "get_action": ("GET", "/Actions", "actions", "get"),
    "create_action": ("POST", "/Actions", "actions", "create"),
}


class HalopsaNode(WorkflowNode):
    integration_type = "automation-halopsa"
    connection_evidence = ConnectionEvidence(
        noun="HaloPSA clients", operation="list_clients"
    )

    @classmethod
    def get_config_model(cls):
        return HalopsaFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a HaloPSA access token")
        credential = self.config.credentials
        config = self.config.config
        method, path, collection, mode = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        params, body = {}, None
        if mode == "get":
            path += "/" + str(values.pop("id"))
            params = values
        elif mode == "list":
            params = values
            if collection != "actions":
                params["pageinate"] = "true"  # Halo's published parameter spelling.
        else:
            # Halo creates and updates through the same array POST; an id selects an update.
            body = [values]
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    credential.instance_url + "/api" + path,
                    params=params,
                    json=body if body is not None else None,
                    headers={
                        "Authorization": "Bearer " + credential.access_token,
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError:
            raise ValueError(
                "HaloPSA request failed; check the instance and connection"
            ) from None
        if not 200 <= response.status_code < 300:
            raise ValueError(
                f"HaloPSA rejected the request (HTTP {response.status_code})"
            )
        if (
            len(response.content) > 8_000_000
            or response.headers.get("content-type", "").split(";")[0]
            != "application/json"
        ):
            raise ValueError("Expected a bounded JSON response from HaloPSA")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("HaloPSA returned invalid JSON") from None
        if (
            not isinstance(data, (dict, list))
            or isinstance(data, dict)
            and any(k in data for k in ("error", "errors"))
        ):
            raise ValueError("HaloPSA did not confirm the request")

        # Do not expose an echoed credential, including in unexpected provider fields.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.access_token, "[redacted]")
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {
                    k: redact(v)
                    for k, v in value.items()
                    if k.lower()
                    not in {
                        "access_token",
                        "refresh_token",
                        "password",
                        "client_secret",
                    }
                }
            return value

        result = {"operation": config.operation, "data": redact(data)}
        if mode == "list":
            rows = data.get(collection) if isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise ValueError("HaloPSA returned an unexpected list envelope")
            result["items"] = redact(rows)
            if collection != "actions":
                count = data.get("record_count") if isinstance(data, dict) else None
                result["next_page"] = (
                    config.page_no + 1
                    if (
                        isinstance(count, int)
                        and config.page_no * config.page_size < count
                    )
                    or (count is None and len(rows) == config.page_size)
                    else None
                )
        return result

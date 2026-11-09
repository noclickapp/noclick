"""Control D account, profile and DNS policy operations from API contract 1.0.1.

Each operation makes one request to the fixed provider origin. Pasted bearer
API tokens support manual connections without an OAuth application.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.controld.com"
CREDENTIAL_TYPE = "control_d_api_token"


class ControlDAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Control D API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.controld.com/reference",
            "x-credential-instructions": "Create an API token in your Control D account and paste it here without the Bearer prefix. Read access is sufficient for reads; writes require a token with write access and the relevant account permissions.",
        })
    credential_type: Literal["control_d_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste a Control D API token")
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

    @field_validator("*", mode="after")
    @classmethod
    def bounded_text(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use text without control characters")
        return value


class _Profile(_Input):
    profile_id: str = Field(..., min_length=1, max_length=255, title="Profile ID")


class _Rule(_Profile):
    do: Literal[0, 1, 2, 3] = Field(..., title="Rule action", description="0 block, 1 bypass, 2 spoof, 3 redirect.")
    status: Literal[0, 1] = Field(..., title="Enabled", description="0 disabled, 1 enabled.")
    via: str | None = Field(None, max_length=255, description="Spoof IP/hostname or redirect proxy ID.")

    @model_validator(mode="after")
    def target_required(self):
        if self.do in (2, 3) and not self.via:
            raise ValueError("Spoof and redirect rules need a via target")
        return self


class GetUser(_Input):
    operation: Literal["get_user"] = "get_user"


class ListProfiles(_Input):
    operation: Literal["list_profiles"] = "list_profiles"


class CreateProfile(_Input):
    operation: Literal["create_profile"] = "create_profile"
    name: str = Field(..., min_length=1, max_length=255)
    clone_profile_id: str | None = Field(None, min_length=1, max_length=255)


class UpdateProfile(_Profile):
    operation: Literal["update_profile"] = "update_profile"
    name: str | None = Field(None, min_length=1, max_length=255)
    disable_ttl: int | None = Field(None, ge=0, description="Disable until this Unix timestamp; 0 clears a previous deactivation.")

    @model_validator(mode="after")
    def has_update(self):
        if self.name is None and self.disable_ttl is None:
            raise ValueError("Supply a name or disable timestamp")
        return self


class DeleteProfile(_Profile):
    operation: Literal["delete_profile"] = "delete_profile"


class ListProfileOptions(_Input):
    operation: Literal["list_profile_options"] = "list_profile_options"


class UpdateProfileOption(_Profile):
    operation: Literal["update_profile_option"] = "update_profile_option"
    option: str = Field(..., min_length=1, max_length=255, title="Option name")
    status: Literal[0, 1]
    value: str | None = Field(None, max_length=4096)


class ListFilters(_Profile):
    operation: Literal["list_filters"] = "list_filters"


class UpdateFilter(_Profile):
    operation: Literal["update_filter"] = "update_filter"
    filter: str = Field(..., min_length=1, max_length=255, title="Filter ID")
    status: Literal[0, 1]


class ListExternalFilters(_Profile):
    operation: Literal["list_external_filters"] = "list_external_filters"


class ListServices(_Profile):
    operation: Literal["list_services"] = "list_services"


class UpdateService(_Rule):
    operation: Literal["update_service"] = "update_service"
    service: str = Field(..., min_length=1, max_length=255, title="Service ID")
    via_v6: str | None = Field(None, max_length=255)


class ListFolders(_Profile):
    operation: Literal["list_folders"] = "list_folders"


class CreateFolder(_Rule):
    operation: Literal["create_folder"] = "create_folder"
    name: str = Field(..., min_length=1, max_length=255)


class UpdateFolder(_Rule):
    operation: Literal["update_folder"] = "update_folder"
    folder: str = Field(..., min_length=1, max_length=255, title="Folder ID")
    name: str | None = Field(None, min_length=1, max_length=255)


class ListRules(_Profile):
    operation: Literal["list_rules"] = "list_rules"
    folder_id: str = Field("0", max_length=255, description="Use 0 for the root folder.")


class CreateRules(_Rule):
    operation: Literal["create_rules"] = "create_rules"
    hostnames: list[str] = Field(..., alias="hostnames[]", min_length=1, max_length=100,
        description="Hostnames to apply the rule to; sent as repeated hostnames[] form fields.")
    group: int | None = Field(None, ge=0, title="Folder ID")
    comment: str | None = Field(None, max_length=64)
    via_v6: str | None = Field(None, max_length=255)

    @field_validator("hostnames")
    @classmethod
    def nonempty_hostnames(cls, value):
        if any(not h or len(h) > 255 or any(c.isspace() or ord(c) < 33 for c in h) for h in value):
            raise ValueError("Supply nonempty hostnames of at most 255 characters")
        return value


class UpdateRules(CreateRules):
    operation: Literal["update_rules"] = "update_rules"
    clear_comment: bool = Field(False, description="Clear the existing comment by sending an empty comment field. Overrides Comment.")


class DeleteRule(_Profile):
    operation: Literal["delete_rule"] = "delete_rule"
    hostname: str = Field(..., min_length=1, max_length=255)


class GetDefaultRule(_Profile):
    operation: Literal["get_default_rule"] = "get_default_rule"


class UpdateDefaultRule(_Rule):
    operation: Literal["update_default_rule"] = "update_default_rule"


class ListDevices(_Input):
    operation: Literal["list_devices"] = "list_devices"


class CreateDevice(_Input):
    operation: Literal["create_device"] = "create_device"
    name: str = Field(..., min_length=1, max_length=255)
    client_count: str = Field(..., pattern=r"^[0-9]+$", max_length=10, description="Number of clients using this endpoint.")
    profile_id: str = Field(..., min_length=1, max_length=255)
    icon: str = Field(..., min_length=1, max_length=255, description="Control D endpoint type, e.g. mobile-android.")
    profile_id2: str | None = Field(None, min_length=1, max_length=255)
    stats: Literal[0, 1, 2] | None = None
    learn_ip: Literal[0, 1] | None = None
    restricted: Literal[0, 1] | None = None
    legacy_ipv4_status: Literal[0, 1] | None = None
    desc: str | None = Field(None, max_length=4096, title="Description")


class UpdateDevice(_Input):
    operation: Literal["update_device"] = "update_device"
    device_id: str = Field(..., min_length=1, max_length=255)
    name: str | None = Field(None, min_length=1, max_length=255)
    profile_id: str | None = Field(None, min_length=1, max_length=255)
    profile_id2: str | None = Field(None, min_length=1, max_length=255, description="Use -1 to remove the second profile.")
    stats: Literal[0, 1, 2] | None = None
    status: Literal[0, 1, 2, 3] | None = Field(None, description="0 pending, 1 active, 2 soft disabled, 3 hard disabled.")
    learn_ip: Literal[0, 1] | None = None
    restricted: Literal[0, 1] | None = None
    legacy_ipv4_status: Literal[0, 1] | None = None
    desc: str | None = Field(None, max_length=4096, title="Description")

    @model_validator(mode="after")
    def has_update(self):
        if not any(v is not None for k, v in self.model_dump().items() if k not in {"operation", "device_id"}):
            raise ValueError("Supply at least one endpoint setting to change")
        return self


class DeleteDevice(_Input):
    operation: Literal["delete_device"] = Field("delete_device", description="Breaks DNS on clients using this endpoint's resolvers.")
    device_id: str = Field(..., min_length=1, max_length=255)


ControlDConfig = Annotated[Union[
    GetUser, ListProfiles, CreateProfile, UpdateProfile, DeleteProfile,
    ListProfileOptions, UpdateProfileOption, ListFilters, UpdateFilter,
    ListExternalFilters, ListServices, UpdateService, ListFolders, CreateFolder,
    UpdateFolder, ListRules, CreateRules, UpdateRules, DeleteRule, GetDefaultRule,
    UpdateDefaultRule, ListDevices, CreateDevice, UpdateDevice, DeleteDevice,
], Field(discriminator="operation")]


class ControlDFullConfig(NodeConfig[ControlDConfig, ControlDAPITokenCredential]):
    pass


# Route placeholders are config fields; all remaining fields are form fields.
ROUTES = {
    "get_user": ("GET", "/users"),
    "list_profiles": ("GET", "/profiles"),
    "create_profile": ("POST", "/profiles"),
    "update_profile": ("PUT", "/profiles/{profile_id}"),
    "delete_profile": ("DELETE", "/profiles/{profile_id}"),
    "list_profile_options": ("GET", "/profiles/options"),
    "update_profile_option": ("PUT", "/profiles/{profile_id}/options/{option}"),
    "list_filters": ("GET", "/profiles/{profile_id}/filters"),
    "update_filter": ("PUT", "/profiles/{profile_id}/filters/filter/{filter}"),
    "list_external_filters": ("GET", "/profiles/{profile_id}/filters/external"),
    "list_services": ("GET", "/profiles/{profile_id}/services"),
    "update_service": ("PUT", "/profiles/{profile_id}/services/{service}"),
    "list_folders": ("GET", "/profiles/{profile_id}/groups"),
    "create_folder": ("POST", "/profiles/{profile_id}/groups"),
    "update_folder": ("PUT", "/profiles/{profile_id}/groups/{folder}"),
    "list_rules": ("GET", "/profiles/{profile_id}/rules/{folder_id}"),
    "create_rules": ("POST", "/profiles/{profile_id}/rules"),
    "update_rules": ("PUT", "/profiles/{profile_id}/rules"),
    "delete_rule": ("DELETE", "/profiles/{profile_id}/rules/{hostname}"),
    "get_default_rule": ("GET", "/profiles/{profile_id}/default"),
    "update_default_rule": ("PUT", "/profiles/{profile_id}/default"),
    "list_devices": ("GET", "/devices"),
    "create_device": ("POST", "/devices"),
    "update_device": ("PUT", "/devices/{device_id}"),
    "delete_device": ("DELETE", "/devices/{device_id}"),
}


class ControlDNode(WorkflowNode):
    integration_type = "automation-control-d"
    connection_evidence = ConnectionEvidence(
        noun="Control D profiles", operation="list_profiles", identity_operation="get_user")

    @classmethod
    def get_config_model(cls):
        return ControlDFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Control D API token")
        config = self.config.config
        method, path = ROUTES[config.operation]
        fields = config.model_dump(by_alias=True, exclude_none=True, exclude={"operation", "clear_comment"})
        if isinstance(config, UpdateRules) and config.clear_comment:
            fields["comment"] = ""
        for key in tuple(fields):
            if "{" + key + "}" in path:
                value = str(fields.pop(key))
                if value in {".", ".."}:
                    raise ValueError("Use a resource ID, not a path segment")
                path = path.replace("{" + key + "}", quote(value, safe=""))
        headers = {
            "Authorization": "Bearer " + self.config.credentials.api_token,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        kwargs = {"content": urlencode(fields, doseq=True)} if method in {"POST", "PUT"} else {}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection, while excluding an echoed token.
            message = response.text[:2000].replace(self.config.credentials.api_token, "[redacted]")
            return {"status": "error", "status_code": response.status_code, "error": message}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Control D returned a non-JSON response") from None
        if not isinstance(payload, dict) or type(payload.get("success")) is not bool:
            raise ValueError("Control D returned an invalid response envelope")
        if not payload["success"]:
            message = str(payload.get("message") or payload.get("error") or "Control D rejected the request")
            return {"status": "error", "error": message.replace(self.config.credentials.api_token, "[redacted]")}
        if "body" not in payload:
            raise ValueError("Control D response is missing its body")
        return {"status": "success", "operation": config.operation, "data": payload["body"],
            **({"message": payload["message"]} if "message" in payload else {})}

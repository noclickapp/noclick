"""App Center v0.1 contract operations and a scoped crash-group poll trigger.

Microsoft has retired App Center. This adapter targets the published legacy
contract; a successful contract check does not establish service availability.
Contract: https://api.appcenter.ms/preview/swagger.json
Token docs: https://learn.microsoft.com/en-us/appcenter/api-docs/
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.appcenter.ms"
APP = "/v0.1/apps/{owner_name}/{app_name}"
GROUP = APP + "/distribution_groups/{distribution_group_name}"
CRASH = APP + "/crash_groups/{crash_group_id}"


class AppCenterTokenCredential(BaseModel):
    model_config = ConfigDict(title="App Center User API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://learn.microsoft.com/en-us/appcenter/api-docs/#creating-an-app-center-user-api-token",
            "x-credential-instructions": "Paste an existing App Center User API token. Read-only tokens support reads; writes need Full Access and the corresponding account permissions. The token is sent in X-API-Token to api.appcenter.ms. Microsoft has retired App Center; this integration targets its legacy API contract.",
        })
    credential_type: Literal["appcenter_api_token"] = Field("appcenter_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="User API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("owner_name", "app_name", "org_name", "distribution_group_name", "crash_group_id", mode="before", check_fields=False)
    @classmethod
    def segment(cls, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 256 or value in {".", ".."} or any(ord(c) < 32 or c in "/\\?#" for c in value):
            raise ValueError("Use a single App Center name or ID, without a URL")
        return value


class _App(_Input):
    owner_name: str = Field(..., title="Owner name", min_length=1, description="User or organization name from the App Center app URL.")
    app_name: str = Field(..., title="App name", min_length=1, description="App URL name, rather than its display name.")


class _Group(_App):
    distribution_group_name: str = Field(..., title="Distribution group name", min_length=1)


class GetUser(_Input):
    operation: Literal["get_user"] = "get_user"


class ListApps(_Input):
    operation: Literal["list_apps"] = "list_apps"
    order_by: Literal["display_name", "name"] | None = None


class GetApp(_App):
    operation: Literal["get_app"] = "get_app"


class CreateApp(_Input):
    operation: Literal["create_app"] = "create_app"
    display_name: str = Field(..., min_length=1)
    os: Literal["Android", "iOS", "macOS", "Tizen", "tvOS", "Windows", "Linux", "Custom"]
    platform: Literal["Java", "Objective-C-Swift", "UWP", "Cordova", "React-Native", "Xamarin", "Unity", "Electron", "WPF", "WinForms", "Custom"]
    name: str | None = None
    description: str | None = None
    release_type: str | None = None


class UpdateApp(_App):
    operation: Literal["update_app"] = "update_app"
    display_name: str | None = None
    description: str | None = None
    release_type: str | None = None


class ListOrganizations(_Input):
    operation: Literal["list_organizations"] = "list_organizations"


class GetOrganization(_Input):
    operation: Literal["get_organization"] = "get_organization"
    org_name: str = Field(..., min_length=1)


class ListReleases(_App):
    operation: Literal["list_releases"] = "list_releases"
    published_only: bool | None = None
    scope: Literal["tester"] | None = None
    top: int = Field(100, ge=1, le=1000)
    release_id: int | None = Field(None, ge=1, description="Optional releaseId filter.")


class GetRelease(_App):
    operation: Literal["get_release"] = "get_release"
    release_id: str = Field(..., min_length=1, pattern=r"^(latest|[1-9][0-9]*)$", description="Numeric release ID or latest.")


class UpdateRelease(_App):
    operation: Literal["update_release"] = "update_release"
    release_id: int = Field(..., ge=1)
    release_notes: str | None = None
    enabled: bool | None = None


class Destination(_Input):
    id: str = Field(..., min_length=1, title="Destination ID")


class DistributeRelease(_App):
    operation: Literal["distribute_release"] = "distribute_release"
    release_id: int = Field(..., ge=1)
    destinations: list[Destination] = Field(..., min_length=1, max_length=100,
        description="Distribution group or store IDs; sends the release to these destinations.")
    notify_testers: bool = Field(True, description="Email testers about the release.")
    mandatory_update: bool | None = None
    release_notes: str | None = None


class ListDistributionGroups(_App):
    operation: Literal["list_distribution_groups"] = "list_distribution_groups"


class GetDistributionGroup(_Group):
    operation: Literal["get_distribution_group"] = "get_distribution_group"


class CreateDistributionGroup(_App):
    operation: Literal["create_distribution_group"] = "create_distribution_group"
    name: str = Field(..., min_length=1)
    display_name: str | None = None


class UpdateDistributionGroup(_Group):
    operation: Literal["update_distribution_group"] = "update_distribution_group"
    name: str | None = None
    is_public: bool | None = Field(None, description="Making a group public changes who can access its releases.")


class ListGroupMembers(_Group):
    operation: Literal["list_group_members"] = "list_group_members"
    exclude_pending_invitations: bool | None = None


class AddGroupMembers(_Group):
    operation: Literal["add_group_members"] = "add_group_members"
    user_emails: list[str] = Field(..., min_length=1, max_length=100, description="Tester email addresses; App Center may send invitations.")


class _CrashList(_App):
    last_occurrence_from: datetime | None = None
    last_occurrence_to: datetime | None = None
    app_version: str | None = None
    group_status: Literal["open", "closed", "ignored"] | None = None

    @field_validator("last_occurrence_from", "last_occurrence_to")
    @classmethod
    def timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Include a timezone in the ISO 8601 timestamp")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.last_occurrence_from and self.last_occurrence_to and self.last_occurrence_from > self.last_occurrence_to:
            raise ValueError("Last-occurrence end must be after start")
        return self


class ListCrashGroups(_CrashList):
    operation: Literal["list_crash_groups"] = "list_crash_groups"
    order_by: Literal["last_occurrence asc", "last_occurrence desc", "count asc", "count desc", "display_id asc", "display_id desc", "impacted_users asc", "impacted_users desc"] = "last_occurrence desc"
    continuation_token: str | None = None


class GetCrashGroup(_App):
    operation: Literal["get_crash_group"] = "get_crash_group"
    crash_group_id: str = Field(..., min_length=1)


class UpdateCrashGroup(GetCrashGroup):
    operation: Literal["update_crash_group"] = "update_crash_group"
    status: Literal["open", "closed", "ignored"] | None = None
    annotation: str | None = None


class OnNewOrUpdatedCrashGroup(PollTriggerConfigBase, _CrashList):
    # Canvas metadata is outside the declared poll scope.
    model_config = ConfigDict(extra="ignore", json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_new_or_updated_crash_group"] = Field("on_new_or_updated_crash_group",
        title="On New or Updated Crash Group", json_schema_extra={"ui:hidden": True,
            "x-is-trigger": True, "x-display-name": "On New or Updated Crash Group", "x-category": "Triggers"})


AppCenterConfig = Annotated[Union[GetUser, ListApps, GetApp, CreateApp, UpdateApp,
    ListOrganizations, GetOrganization, ListReleases, GetRelease, UpdateRelease,
    DistributeRelease, ListDistributionGroups, GetDistributionGroup,
    CreateDistributionGroup, UpdateDistributionGroup, ListGroupMembers,
    AddGroupMembers, ListCrashGroups, GetCrashGroup, UpdateCrashGroup,
    OnNewOrUpdatedCrashGroup], Field(discriminator="operation")]


class AppCenterNodeConfig(NodeConfig[AppCenterConfig, AppCenterTokenCredential]):
    pass


# Each entry is exactly one operation of the pinned v0.1 Swagger contract.
# (method, path, query-field -> wire-name, body fields, provider operationId)
OPERATIONS = {
    "get_user": ("GET", "/v0.1/user", {}, (), "users_get"),
    "list_apps": ("GET", "/v0.1/apps", {"order_by": "$orderBy"}, (), "apps_list"),
    "get_app": ("GET", APP, {}, (), "apps_get"),
    "create_app": ("POST", "/v0.1/apps", {}, ("display_name", "os", "platform", "name", "description", "release_type"), "apps_create"),
    "update_app": ("PATCH", APP, {}, ("display_name", "description", "release_type"), "apps_update"),
    "list_organizations": ("GET", "/v0.1/orgs", {}, (), "organizations_list"),
    "get_organization": ("GET", "/v0.1/orgs/{org_name}", {}, (), "organizations_get"),
    "list_releases": ("GET", APP + "/releases", {"published_only": "published_only", "scope": "scope", "top": "top", "release_id": "releaseId"}, (), "releases_list"),
    "get_release": ("GET", APP + "/releases/{release_id}", {}, (), "releases_getLatestByUser"),
    "update_release": ("PUT", APP + "/releases/{release_id}", {}, ("release_notes", "enabled"), "releases_updateDetails"),
    # Preview Swagger says text/plain; Microsoft's CLI explicitly sends JSON:
    # https://github.com/microsoft/appcenter-cli/blob/master/src/util/apis/generated/src/operations/releases.ts#L888-L915
    "distribute_release": ("PATCH", APP + "/releases/{release_id}", {}, ("destinations", "notify_testers", "mandatory_update", "release_notes"), "releases_update"),
    "list_distribution_groups": ("GET", APP + "/distribution_groups", {}, (), "distributionGroups_list"),
    "get_distribution_group": ("GET", GROUP, {}, (), "distributionGroups_get"),
    "create_distribution_group": ("POST", APP + "/distribution_groups", {}, ("name", "display_name"), "distributionGroups_create"),
    "update_distribution_group": ("PATCH", GROUP, {}, ("name", "is_public"), "distributionGroups_update"),
    "list_group_members": ("GET", GROUP + "/members", {"exclude_pending_invitations": "exclude_pending_invitations"}, (), "distributionGroups_listUsers"),
    "add_group_members": ("POST", GROUP + "/members", {}, ("user_emails",), "distributionGroups_addUser"),
    "list_crash_groups": ("GET", APP + "/crash_groups", {"last_occurrence_from": "last_occurrence_from", "last_occurrence_to": "last_occurrence_to", "app_version": "app_version", "group_status": "group_status", "order_by": "$orderby", "continuation_token": "continuation_token"}, (), "crashGroups_list"),
    "get_crash_group": ("GET", CRASH, {}, (), "crashGroups_get"),
    "update_crash_group": ("PATCH", CRASH, {}, ("status", "annotation"), "crashGroups_update"),
}


class AppCenterNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-appcenter"
    connection_evidence = ConnectionEvidence(noun="apps", operation="list_apps",
        identity_operation="get_user", identity_keys=("display_name", "email", "name"))

    @classmethod
    def get_config_model(cls):
        return AppCenterNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an App Center User API token")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params,
                json=body, headers={"X-API-Token": credential.api_token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for the manual-connect evidence seam.
            message = response.text[:2000].replace(credential.api_token, "[redacted]")
            raise ValueError(f"App Center HTTP {response.status_code}: {message}")
        if not response.content:
            raise ValueError("App Center returned an empty response where JSON was expected")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("App Center returned an unexpected JSON shape")
        if isinstance(data, dict) and "error" in data:
            raise ValueError("App Center error: " + str(data["error"]).replace(credential.api_token, "[redacted]"))
        return data

    @staticmethod
    def _path(template, values):
        for name, value in values.items():
            template = template.replace("{" + name + "}", quote(str(value), safe=""))
        return template

    async def _poll_crash_groups(self, config):
        values = config.model_dump(mode="json", exclude_none=True)
        params = {k: values[k] for k in ("last_occurrence_from", "last_occurrence_to", "app_version", "group_status") if k in values}
        params["$orderby"] = "last_occurrence desc"
        groups, cursors = [], set()
        for _ in range(20):
            data = await self._request("GET", self._path(APP + "/crash_groups", values), params=params)
            if not isinstance(data, dict) or not isinstance(data.get("crash_groups"), list):
                raise ValueError("App Center crash-group list is invalid")
            groups.extend(data["crash_groups"])
            cursor = data.get("continuation_token")
            if not cursor:
                if data.get("limited_result_set"):
                    raise ValueError("App Center truncated crash groups; narrow the last-occurrence window")
                break
            if not isinstance(cursor, str) or cursor in cursors:
                raise ValueError("App Center returned a nonadvancing continuation token")
            cursors.add(cursor)
            params["continuation_token"] = cursor
        else:
            raise ValueError("App Center exceeded 20 pages; narrow the last-occurrence window")
        if any(not isinstance(row, dict) or not row.get("crash_group_id") or not row.get("last_occurrence") for row in groups):
            raise ValueError("App Center crash group is missing its ID or last occurrence")
        fresh = await self._filter_unseen(groups, lambda row: json.dumps([
            row["crash_group_id"], row["last_occurrence"], row.get("count"), row.get("status"), row.get("annotation")], separators=(",", ":")))
        return {"crash_groups": fresh, "new_or_updated_count": len(fresh),
            "owner_name": config.owner_name, "app_name": config.app_name}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_or_updated_crash_group":
            return bool(output.get("new_or_updated_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        groups = output.get("crash_groups")
        if not isinstance(groups, list):
            return super().resolve_agent_event(output)
        if not groups:
            return None
        lines = [f"- Crash group {row['crash_group_id']}: {row.get('crash_reason', '')}; "
                 f"version {row.get('app_version', '')}, count {row.get('count', '')}, "
                 f"last occurred {row['last_occurrence']}, status {row.get('status', '')}." for row in groups[:20]]
        return {"text": f"App Center: {len(groups)} new or updated crash group(s) in "
            f"{output.get('owner_name')}/{output.get('app_name')}:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect an App Center User API token")
        config = self.config.config
        if isinstance(config, OnNewOrUpdatedCrashGroup):
            return await self._poll_crash_groups(config)
        method, path, query, body_fields, _ = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        params = {wire: values[name] for name, wire in query.items() if name in values}
        body = {name: values[name] for name in body_fields if name in values} if body_fields else None
        if body_fields and not body:
            raise ValueError("Supply at least one field to update")
        data = await self._request(method, self._path(path, values), params=params, body=body)
        return {"data": data}

"""Okta Management API: users, groups, app assignments and lifecycle.

API reference: https://developer.okta.com/docs/api/openapi/okta-management/
Authentication: pasted SSWS API token (inherits its creator's admin permissions).
Each operation performs one documented API call. Lists return one page and the
opaque next_after cursor; they never follow a URL supplied by the provider.
"""

import json
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import https_origin
from utils.ssrf import guarded_async_client, normalize_https_origin


class OktaAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Okta API Token", json_schema_extra={
        "x-credential-url": "https://developer.okta.com/docs/guides/create-an-api-token/main/",
        "x-credential-instructions": "In your Okta Admin Console, open Security → API → Tokens and create a token. Paste the token and your organization URL. The token inherits its creator's permissions; use an administrator permitted to manage the resources your workflow needs.",
    })
    credential_type: Literal["okta_api_token"] = Field("okta_api_token", json_schema_extra={"ui:hidden": True})
    org_url: str = Field(..., title="Organization URL", description="Your Okta organization URL, such as https://example.okta.com. Custom domains are supported. Use the organization host, not the -admin host.")
    api_token: str = Field(..., title="API Token", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("org_url")
    @classmethod
    def normalize_org(cls, value: str) -> str:
        origin = normalize_https_origin(https_origin(value, field_name="Organization URL"), field_name="Organization URL")
        if "-admin." in urlsplit(origin).hostname:
            raise ValueError("Use your Okta organization URL without -admin in the hostname.")
        return origin


def _resource(title: str, key: str):
    return Field(..., title=title, min_length=1, json_schema_extra={"x-dynamic-options": {
        "field_name": key, "searchable": True, "allow_custom": True,
        "placeholder": f"Select {title.lower()}...",
    }})


class OktaPageConfig(BaseModel):
    limit: int = Field(100, ge=1, le=200, title="Page Size", description="Maximum items in this page. Pass next_after into After to read another page.")
    after: Optional[str] = Field(None, title="After", description="Opaque cursor from the previous page's next_after.")


class OktaListUsersConfig(OktaPageConfig):
    operation: Literal["list_users"] = "list_users"
    search: Optional[str] = Field(None, title="Search", description='Okta search expression, for example profile.lastName eq "Brock". Search is eventually consistent.')
    filter: Optional[str] = Field(None, title="Filter", description="Okta filter expression. Use either Search or Filter.")


class OktaGetUserConfig(BaseModel):
    operation: Literal["get_user"] = "get_user"
    user_id: str = _resource("User", "user_id")


class OktaCreateUserConfig(BaseModel):
    operation: Literal["create_user"] = "create_user"
    first_name: str = Field(..., title="First Name", min_length=1)
    last_name: str = Field(..., title="Last Name", min_length=1)
    email: str = Field(..., title="Email", min_length=1)
    login: str = Field(..., title="Login", min_length=1)
    activate: bool = Field(False, title="Activate", description="Activate immediately. Okta may send an activation email; leave off to create a staged user.")


class OktaUpdateUserConfig(BaseModel):
    operation: Literal["update_user"] = "update_user"
    user_id: str = _resource("User", "user_id")
    profile_json: str = Field(..., title="Profile", description='JSON object of profile attributes to update, for example {"firstName":"Isaac"}. Uses partial update; omitted attributes are preserved.', json_schema_extra={"ui:widget": "textarea"})


class OktaActivateUserConfig(BaseModel):
    operation: Literal["activate_user"] = "activate_user"
    user_id: str = _resource("User", "user_id")
    send_email: bool = Field(False, title="Send Email", description="Send the activation email. When off, Okta returns an activation token and URL.")


class OktaDeactivateUserConfig(BaseModel):
    operation: Literal["deactivate_user"] = "deactivate_user"
    user_id: str = _resource("User", "user_id")
    send_email: bool = Field(False, title="Send Email", description="Send an administrator notification when deactivation completes. Deactivation removes app access and may delete app data.")


class OktaSuspendUserConfig(BaseModel):
    operation: Literal["suspend_user"] = "suspend_user"
    user_id: str = _resource("User", "user_id")


class OktaUnsuspendUserConfig(BaseModel):
    operation: Literal["unsuspend_user"] = "unsuspend_user"
    user_id: str = _resource("User", "user_id")


class OktaListUserGroupsConfig(BaseModel):
    operation: Literal["list_user_groups"] = "list_user_groups"
    user_id: str = _resource("User", "user_id")


class OktaListGroupsConfig(OktaPageConfig):
    operation: Literal["list_groups"] = "list_groups"
    search: Optional[str] = Field(None, title="Search", description="Okta group search expression. Search is eventually consistent.")
    filter: Optional[str] = Field(None, title="Filter", description="Okta filter expression. Use either Search or Filter.")


class OktaGetGroupConfig(BaseModel):
    operation: Literal["get_group"] = "get_group"
    group_id: str = _resource("Group", "group_id")


class OktaCreateGroupConfig(BaseModel):
    operation: Literal["create_group"] = "create_group"
    name: str = Field(..., title="Name", min_length=1)
    description: Optional[str] = Field(None, title="Description")


class OktaDeleteGroupConfig(BaseModel):
    operation: Literal["delete_group"] = "delete_group"
    group_id: str = _resource("Group", "group_id")


class OktaListGroupUsersConfig(OktaPageConfig):
    operation: Literal["list_group_users"] = "list_group_users"
    group_id: str = _resource("Group", "group_id")


class OktaAddUserToGroupConfig(BaseModel):
    operation: Literal["add_user_to_group"] = "add_user_to_group"
    group_id: str = _resource("Group", "group_id")
    user_id: str = _resource("User", "user_id")


class OktaRemoveUserFromGroupConfig(BaseModel):
    operation: Literal["remove_user_from_group"] = "remove_user_from_group"
    group_id: str = _resource("Group", "group_id")
    user_id: str = _resource("User", "user_id")


class OktaListAppsConfig(OktaPageConfig):
    operation: Literal["list_apps"] = "list_apps"
    q: Optional[str] = Field(None, title="Name Prefix", description="Filter applications by label or name prefix.")


class OktaListAppUsersConfig(OktaPageConfig):
    operation: Literal["list_app_users"] = "list_app_users"
    app_id: str = _resource("Application", "app_id")


class OktaAssignUserToAppConfig(BaseModel):
    operation: Literal["assign_user_to_app"] = "assign_user_to_app"
    app_id: str = _resource("Application", "app_id")
    user_id: str = _resource("User", "user_id")
    username: Optional[str] = Field(None, title="Application Username", description="Optional app login. Okta applies the application's username mapping when omitted.")
    profile_json: Optional[str] = Field(None, title="Application Profile", description="JSON object of app-specific profile attributes required by your application.", json_schema_extra={"ui:widget": "textarea"})


class OktaUnassignUserFromAppConfig(BaseModel):
    operation: Literal["unassign_user_from_app"] = "unassign_user_from_app"
    app_id: str = _resource("Application", "app_id")
    user_id: str = _resource("User", "user_id")
    send_email: bool = Field(False, title="Send Email", description="Send an email notification when removing the assignment.")


OktaConfig = Annotated[Union[
    OktaListUsersConfig, OktaGetUserConfig, OktaCreateUserConfig, OktaUpdateUserConfig,
    OktaActivateUserConfig, OktaDeactivateUserConfig, OktaSuspendUserConfig, OktaUnsuspendUserConfig,
    OktaListUserGroupsConfig, OktaListGroupsConfig, OktaGetGroupConfig, OktaCreateGroupConfig,
    OktaDeleteGroupConfig, OktaListGroupUsersConfig, OktaAddUserToGroupConfig, OktaRemoveUserFromGroupConfig,
    OktaListAppsConfig, OktaListAppUsersConfig, OktaAssignUserToAppConfig, OktaUnassignUserFromAppConfig,
], Field(discriminator="operation")]


class OktaNodeConfig(NodeConfig[OktaConfig, OktaAPITokenCredential]):
    pass


# operation -> HTTP method, documented path, output collection (None for a single resource).
OKTA_OPERATIONS = {
    "list_users": ("GET", "/api/v1/users", "users"),
    "get_user": ("GET", "/api/v1/users/{user_id}", None),
    "create_user": ("POST", "/api/v1/users", None),
    "update_user": ("POST", "/api/v1/users/{user_id}", None),
    "activate_user": ("POST", "/api/v1/users/{user_id}/lifecycle/activate", None),
    "deactivate_user": ("POST", "/api/v1/users/{user_id}/lifecycle/deactivate", None),
    "suspend_user": ("POST", "/api/v1/users/{user_id}/lifecycle/suspend", None),
    "unsuspend_user": ("POST", "/api/v1/users/{user_id}/lifecycle/unsuspend", None),
    "list_user_groups": ("GET", "/api/v1/users/{user_id}/groups", "groups"),
    "list_groups": ("GET", "/api/v1/groups", "groups"),
    "get_group": ("GET", "/api/v1/groups/{group_id}", None),
    "create_group": ("POST", "/api/v1/groups", None),
    "delete_group": ("DELETE", "/api/v1/groups/{group_id}", None),
    "list_group_users": ("GET", "/api/v1/groups/{group_id}/users", "users"),
    "add_user_to_group": ("PUT", "/api/v1/groups/{group_id}/users/{user_id}", None),
    "remove_user_from_group": ("DELETE", "/api/v1/groups/{group_id}/users/{user_id}", None),
    "list_apps": ("GET", "/api/v1/apps", "applications"),
    "list_app_users": ("GET", "/api/v1/apps/{app_id}/users", "users"),
    "assign_user_to_app": ("POST", "/api/v1/apps/{app_id}/users", None),
    "unassign_user_from_app": ("DELETE", "/api/v1/apps/{app_id}/users/{user_id}", None),
}
_BODYLESS = {"deactivate_user", "suspend_user", "unsuspend_user", "delete_group", "add_user_to_group", "remove_user_from_group", "unassign_user_from_app"}


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Profile must be a valid JSON object") from None
    if not isinstance(value, dict) or not value:
        raise ValueError("Profile must be a nonempty JSON object")
    return value


async def _okta_request(credentials, operation, path, params=None, body=None):
    method, _, collection = OKTA_OPERATIONS[operation]
    start = time.monotonic()
    def error(message, code=None):
        return {"status": "error", "action": operation, "error": message, "status_code": code,
                "timing_ms": {"api_request": round((time.monotonic() - start) * 1000, 2)}}
    try:
        async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(method, credentials.org_url + path,
                headers={"Authorization": f"SSWS {credentials.api_token}", "Accept": "application/json", "Content-Type": "application/json"},
                params={k: v for k, v in (params or {}).items() if v is not None and v != ""}, json=body)
        code = response.status_code
        if not 200 <= code < 300:
            # Never reflect headers, URLs, token values, or arbitrary provider text.
            return error(f"Okta API request failed (HTTP {code})", code)
        if operation in _BODYLESS:
            data = {"success": True}
        else:
            try:
                data = response.json()
            except ValueError:
                return error("Okta returned invalid JSON", code)
            if collection:
                if not isinstance(data, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in data):
                    return error("Okta returned an invalid resource list", code)
                # Cursor only: no URL or host from a Link header is ever requested.
                next_url = response.links.get("next", {}).get("url", "")
                next_after = parse_qs(urlsplit(next_url).query).get("after", [None])[0]
                data = {collection: data, "count": len(data), "next_after": next_after}
            elif not isinstance(data, dict) or "errorCode" in data or "errorSummary" in data:
                return error("Okta returned an invalid resource", code)
            elif operation != "activate_user" and not isinstance(data.get("id"), str):
                return error("Okta returned an invalid resource", code)
        return {"status": "success", "action": operation, "data": data, "status_code": code,
                "timing_ms": {"api_request": round((time.monotonic() - start) * 1000, 2)}}
    except Exception:
        return error("Could not reach the Okta API")


class OktaNode(WorkflowNode):
    integration_type = "automation-okta"
    credential_provider_labels = {"okta": "Okta Account"}
    connection_evidence = ConnectionEvidence(field="user_id", noun="users")
    edit_examples = ["Create an Okta user and add them to an onboarding group", "Suspend an Okta user", "Assign a user to an Okta application"]

    @classmethod
    def get_config_model(cls):
        return OktaNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        lookup = {"user_id": ("list_users", "users"), "group_id": ("list_groups", "groups"), "app_id": ("list_apps", "applications")}
        if field_name not in lookup or not credential_data:
            return {"options": []}
        credential = OktaAPITokenCredential.model_validate(credential_data)
        operation, collection = lookup[field_name]
        params = {"limit": 100, "after": page_token, "q": search}
        result = await _okta_request(credential, operation, OKTA_OPERATIONS[operation][1], params)
        if result["status"] != "success":
            raise ValueError(result["error"])
        data = result["data"]
        options = []
        for row in data[collection]:
            profile = row.get("profile") or {}
            label = profile.get("login") or profile.get("name") or row.get("label") or row.get("name") or row["id"]
            options.append({"value": row["id"], "label": label})
        return {"options": options, "next_page_token": data["next_after"]}

    async def execute(self, inputs):
        if not isinstance(self.config, OktaNodeConfig):
            raise ValueError("Valid Okta configuration is required")
        if not self.config.credentials:
            raise ValueError("Credentials are required. Add your Okta API token and organization URL.")
        c = self.config.config
        operation = c.operation
        _, template, _ = OKTA_OPERATIONS[operation]
        path = template.format(**{k: quote(str(v), safe="") for k, v in c.model_dump().items() if k in ("user_id", "group_id", "app_id")})
        params = {k: getattr(c, k) for k in ("limit", "after", "search", "filter", "q") if hasattr(c, k)}
        if params.get("search") and params.get("filter"):
            raise ValueError("Use either Search or Filter, not both")
        body = None
        if operation == "create_user":
            params["activate"] = c.activate
            body = {"profile": {"firstName": c.first_name, "lastName": c.last_name, "email": c.email, "login": c.login}}
        elif operation == "update_user":
            body = {"profile": _json_object(c.profile_json)}
        elif operation == "create_group":
            body = {"profile": {"name": c.name}}
            if c.description is not None:
                body["profile"]["description"] = c.description
        elif operation == "assign_user_to_app":
            body = {"id": c.user_id, "scope": "USER"}
            if c.username:
                body["credentials"] = {"userName": c.username}
            if c.profile_json:
                body["profile"] = _json_object(c.profile_json)
        if hasattr(c, "send_email"):
            params["sendEmail"] = c.send_email
        return await _okta_request(self.config.credentials, operation, path, params, body)

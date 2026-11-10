"""Keycloak Admin REST API: one contract operation per action, supplied bearer token.

Contract: https://www.keycloak.org/docs-api/latest/rest-api/openapi.yaml
Auth: https://www.keycloak.org/docs/latest/server_development/index.html#admin-rest-api
Public HTTPS instances mounted at the origin root are supported. No token minting,
refresh, automatic write retries or implicit email actions are performed.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import SSRFError, guarded_async_client, normalize_https_origin


def _segment(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255 or value in {".", ".."} or any(c in value for c in "/\\?#%") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter one realm name or resource ID without URL delimiters")
    return value


class KeycloakTokenCredential(BaseModel):
    model_config = ConfigDict(title="Keycloak Admin Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.keycloak.org/docs/latest/server_development/index.html#admin-rest-api",
            "x-credential-instructions": "Paste an existing admin access token, your Keycloak HTTPS origin and target realm name (not its ID). The instance must be mounted at the origin root; /auth subpath installations are not supported. Grant only the realm-management roles your actions need: view-realm for the connection read; query-users/view-users and manage-users for users, groups and memberships; query-clients/view-clients for clients; view-events for events. Realm role reads require view-realm. A token from admin-cli expires in one minute by default. NoClick does not mint or refresh tokens: replace it when it expires. Requests use Authorization: Bearer and do not follow redirects."})
    credential_type: Literal["keycloak_token"] = Field("keycloak_token", json_schema_extra={"ui:hidden": True})
    instance_url: str = Field(..., title="Keycloak Instance URL", description="HTTPS origin such as https://sso.example.com; no admin path, query or fragment.")
    realm: str = Field(..., title="Realm Name", description="Target realm name, not the realm ID.")
    access_token: str = Field(..., repr=False, title="Admin Access Token", json_schema_extra={"ui:widget": "password"})

    @field_validator("instance_url", mode="before")
    @classmethod
    def origin(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter your Keycloak HTTPS origin")
        try:
            return normalize_https_origin(value, field_name="Keycloak instance")
        except SSRFError:
            raise ValueError("Enter an HTTPS origin without userinfo, path, query or fragment") from None

    _realm = field_validator("realm", mode="before")(_segment)

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Admin access token")
        if len(value) > 32768 or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


def _operation(name, category):
    return Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": name.replace("_", " ").title(), "x-category": category, "x-is-trigger": False})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    first: int = Field(0, ge=0, le=2147483647, title="Offset")
    max: int = Field(100, ge=1, le=1000, title="Page Size", description="One page per action. A full page may have more results; advance the offset to continue.")


class _User(_Input):
    user_id: str = Field(..., title="User ID")
    _user_id = field_validator("user_id", mode="before")(_segment)


class _Group(_Input):
    group_id: str = Field(..., title="Group ID")
    _group_id = field_validator("group_id", mode="before")(_segment)


class _UserFields(_Input):
    email: str | None = Field(None, max_length=320)
    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    enabled: bool | None = None
    email_verified: bool | None = None
    attributes: dict[str, list[str]] | None = Field(None, description="Custom user attributes; each value is a list of strings.")


class KeycloakRealmRole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1, max_length=255, description="Role ID from List User Realm Roles or List Realm Roles.")
    name: str = Field(..., min_length=1, max_length=255)
    _id = field_validator("id", mode="before")(_segment)


class KeycloakListRealmsConfig(_Input):
    operation: Literal["list_realms"] = _operation("list_realms", "Realms")


class KeycloakGetRealmConfig(_Input):
    operation: Literal["get_realm"] = _operation("get_realm", "Realms")


class KeycloakListUsersConfig(_Page):
    operation: Literal["list_users"] = _operation("list_users", "Users")
    search: str | None = Field(None, max_length=1000)
    username: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=320)
    exact: bool | None = None
    enabled: bool | None = None
    created_after: str | None = Field(None, pattern=r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,16})$", description="Inclusive ISO date or epoch milliseconds.")


class KeycloakGetUserConfig(_User):
    operation: Literal["get_user"] = _operation("get_user", "Users")


class KeycloakCreateUserConfig(_UserFields):
    operation: Literal["create_user"] = _operation("create_user", "Users")
    username: str = Field(..., min_length=1, max_length=255)


class KeycloakUpdateUserConfig(_User, _UserFields):
    operation: Literal["update_user"] = _operation("update_user", "Users")
    @model_validator(mode="after")
    def changed(self):
        if not any(getattr(self, name) is not None for name in _UserFields.model_fields):
            raise ValueError("Supply at least one user field to update")
        return self


class KeycloakDeleteUserConfig(_User):
    operation: Literal["delete_user"] = _operation("delete_user", "Users")


class KeycloakListUserGroupsConfig(_User, _Page):
    operation: Literal["list_user_groups"] = _operation("list_user_groups", "Memberships")


class KeycloakAddUserToGroupConfig(_User, _Group):
    operation: Literal["add_user_to_group"] = _operation("add_user_to_group", "Memberships")


class KeycloakRemoveUserFromGroupConfig(_User, _Group):
    operation: Literal["remove_user_from_group"] = _operation("remove_user_from_group", "Memberships")


class KeycloakListUserRealmRolesConfig(_User):
    operation: Literal["list_user_realm_roles"] = _operation("list_user_realm_roles", "Roles")


class KeycloakAddUserRealmRolesConfig(_User):
    operation: Literal["add_user_realm_roles"] = _operation("add_user_realm_roles", "Roles")
    roles: list[KeycloakRealmRole] = Field(..., min_length=1, max_length=100, description="Realm role IDs and names; sent as the API role representation array.")


class KeycloakRemoveUserRealmRolesConfig(_User):
    operation: Literal["remove_user_realm_roles"] = _operation("remove_user_realm_roles", "Roles")
    roles: list[KeycloakRealmRole] = Field(..., min_length=1, max_length=100)


class KeycloakListGroupsConfig(_Page):
    operation: Literal["list_groups"] = _operation("list_groups", "Groups")
    search: str | None = Field(None, max_length=1000)
    exact: bool | None = None


class KeycloakGetGroupConfig(_Group):
    operation: Literal["get_group"] = _operation("get_group", "Groups")


class KeycloakCreateGroupConfig(_Input):
    operation: Literal["create_group"] = _operation("create_group", "Groups")
    name: str = Field(..., min_length=1, max_length=255)
    attributes: dict[str, list[str]] | None = None


class KeycloakUpdateGroupConfig(_Group):
    operation: Literal["update_group"] = _operation("update_group", "Groups")
    name: str = Field(..., min_length=1, max_length=255)
    attributes: dict[str, list[str]] | None = None


class KeycloakDeleteGroupConfig(_Group):
    operation: Literal["delete_group"] = _operation("delete_group", "Groups")


class KeycloakListClientsConfig(_Page):
    operation: Literal["list_clients"] = _operation("list_clients", "Clients")
    client_id: str | None = Field(None, max_length=255, description="Public clientId filter, not the internal UUID.")


class KeycloakGetClientConfig(_Input):
    operation: Literal["get_client"] = _operation("get_client", "Clients")
    client_uuid: str = Field(..., title="Internal Client UUID", description="Use id from List Clients, not clientId.")
    _id = field_validator("client_uuid", mode="before")(_segment)


class KeycloakListRealmRolesConfig(_Page):
    operation: Literal["list_realm_roles"] = _operation("list_realm_roles", "Roles")
    search: str | None = Field(None, max_length=1000)


class KeycloakListUserSessionsConfig(_User):
    operation: Literal["list_user_sessions"] = _operation("list_user_sessions", "Sessions")


class KeycloakLogoutUserConfig(_User):
    operation: Literal["logout_user"] = _operation("logout_user", "Sessions")


class KeycloakListEventsConfig(_Page):
    operation: Literal["list_events"] = _operation("list_events", "Events")
    date_from: str | None = Field(None, pattern=r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,16})$")
    date_to: str | None = Field(None, pattern=r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,16})$")
    direction: Literal["asc", "desc"] = "desc"
    user: str | None = Field(None, max_length=255)
    client: str | None = Field(None, max_length=255)
    type: list[str] | None = Field(None, max_length=100, title="Event Types")


class KeycloakOnNewUserConfig(PollTriggerConfigBase):
    operation: Literal["on_new_user"] = Field("on_new_user", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New User"})
    created_after: str | None = Field(None, pattern=r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,16})$", description="Only monitor users created on or after this ISO date or epoch millisecond timestamp. Existing users are baselined when armed. Narrow this window if it exceeds 5,000 users. Requires a Keycloak version supporting createdAfter.")


KeycloakConfig = Annotated[Union[KeycloakListRealmsConfig, KeycloakGetRealmConfig, KeycloakListUsersConfig, KeycloakGetUserConfig, KeycloakCreateUserConfig, KeycloakUpdateUserConfig, KeycloakDeleteUserConfig, KeycloakListUserGroupsConfig, KeycloakAddUserToGroupConfig, KeycloakRemoveUserFromGroupConfig, KeycloakListUserRealmRolesConfig, KeycloakAddUserRealmRolesConfig, KeycloakRemoveUserRealmRolesConfig, KeycloakListGroupsConfig, KeycloakGetGroupConfig, KeycloakCreateGroupConfig, KeycloakUpdateGroupConfig, KeycloakDeleteGroupConfig, KeycloakListClientsConfig, KeycloakGetClientConfig, KeycloakListRealmRolesConfig, KeycloakListUserSessionsConfig, KeycloakLogoutUserConfig, KeycloakListEventsConfig, KeycloakOnNewUserConfig], Field(discriminator="operation")]


class KeycloakNodeConfig(NodeConfig[KeycloakConfig, KeycloakTokenCredential]):
    pass


ROUTES = {
    'list_realms': ('GET', '/admin/realms', (), (), True, (200,)),
    'get_realm': ('GET', '/admin/realms/{realm}', (), (), False, (200,)),
    'list_users': ('GET', '/admin/realms/{realm}/users', ('first', 'max', 'search', 'username', 'email', 'exact', 'enabled', 'created_after'), (), True, (200,)),
    'get_user': ('GET', '/admin/realms/{realm}/users/{user_id}', (), (), False, (200,)),
    'create_user': ('POST', '/admin/realms/{realm}/users', (), ('username', 'email', 'first_name', 'last_name', 'enabled', 'email_verified', 'attributes'), False, (201,)),
    'update_user': ('PUT', '/admin/realms/{realm}/users/{user_id}', (), ('email', 'first_name', 'last_name', 'enabled', 'email_verified', 'attributes'), False, (204,)),
    'delete_user': ('DELETE', '/admin/realms/{realm}/users/{user_id}', (), (), False, (204,)),
    'list_user_groups': ('GET', '/admin/realms/{realm}/users/{user_id}/groups', ('first', 'max'), (), True, (200,)),
    'add_user_to_group': ('PUT', '/admin/realms/{realm}/users/{user_id}/groups/{group_id}', (), (), False, (204,)),
    'remove_user_from_group': ('DELETE', '/admin/realms/{realm}/users/{user_id}/groups/{group_id}', (), (), False, (204,)),
    'list_user_realm_roles': ('GET', '/admin/realms/{realm}/users/{user_id}/role-mappings/realm', (), (), True, (200,)),
    'add_user_realm_roles': ('POST', '/admin/realms/{realm}/users/{user_id}/role-mappings/realm', (), ('roles',), False, (204,)),
    'remove_user_realm_roles': ('DELETE', '/admin/realms/{realm}/users/{user_id}/role-mappings/realm', (), ('roles',), False, (204,)),
    'list_groups': ('GET', '/admin/realms/{realm}/groups', ('first', 'max', 'search', 'exact'), (), True, (200,)),
    'get_group': ('GET', '/admin/realms/{realm}/groups/{group_id}', (), (), False, (200,)),
    'create_group': ('POST', '/admin/realms/{realm}/groups', (), ('name', 'attributes'), False, (201, 204)),
    'update_group': ('PUT', '/admin/realms/{realm}/groups/{group_id}', (), ('name', 'attributes'), False, (204,)),
    'delete_group': ('DELETE', '/admin/realms/{realm}/groups/{group_id}', (), (), False, (204,)),
    'list_clients': ('GET', '/admin/realms/{realm}/clients', ('first', 'max', 'client_id'), (), True, (200,)),
    'get_client': ('GET', '/admin/realms/{realm}/clients/{client_uuid}', (), (), False, (200,)),
    'list_realm_roles': ('GET', '/admin/realms/{realm}/roles', ('first', 'max', 'search'), (), True, (200,)),
    'list_user_sessions': ('GET', '/admin/realms/{realm}/users/{user_id}/sessions', (), (), True, (200,)),
    'logout_user': ('POST', '/admin/realms/{realm}/users/{user_id}/logout', (), (), False, (204,)),
    'list_events': ('GET', '/admin/realms/{realm}/events', ('first', 'max', 'date_from', 'date_to', 'direction', 'user', 'client', 'type'), (), True, (200,)),
}
WIRE_NAMES = {"first_name": "firstName", "last_name": "lastName", "email_verified": "emailVerified", "created_after": "createdAfter", "client_id": "clientId", "date_from": "dateFrom", "date_to": "dateTo"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(row, token) for row in value]
    if isinstance(value, dict):
        return {key: _redact(row, token) for key, row in value.items() if key not in {"secret", "credentials", "password", "access_token", "refresh_token", "registrationAccessToken", "clientSecret", "client_secret", "privateKey", "private_key"}}
    return value


class KeycloakNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-keycloak"
    connection_evidence = ConnectionEvidence(operation="get_realm", identity_operation="get_realm", noun="Keycloak realm", label_keys=("displayName", "realm", "id"), identity_keys=("displayName", "realm", "id"))

    @classmethod
    def get_config_model(cls):
        return KeycloakNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", "keycloak_token") != "keycloak_token":
            raise ValueError("Select a Keycloak admin access token credential")
        return super().parse_config(config_data)

    async def _request(self, method, path, *, params=None, body=None, statuses=(200,), is_list=False):
        credential = self.config.credentials
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.instance_url + path,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.status_code not in statuses:
            # Keep provider rejection text so the connection seam can distinguish
            # rejected credentials from transport and response-shape uncertainty.
            message = "Request rejected"
            if len(response.content) <= 4096:
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        message = data.get("error_description") or data.get("errorMessage") or data.get("error") or message
                except ValueError:
                    pass
            raise ValueError(f"Keycloak API {response.status_code}: {_redact(str(message), credential.access_token)[:1000]}")
        if response.status_code in {201, 204}:
            return {"http_status": response.status_code, "acknowledged": True}
        if len(response.content) > 8_000_000 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected bounded JSON from Keycloak")
        data = response.json()
        if not isinstance(data, list if is_list else dict) or (is_list and any(not isinstance(row, dict) for row in data)):
            raise ValueError("Unexpected Keycloak response shape")
        return {"http_status": response.status_code, "data": data}

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a Keycloak admin access token")
        try:
            if isinstance(config, KeycloakOnNewUserConfig):
                users = []
                path = "/admin/realms/" + quote(credential.realm, safe="") + "/users"
                for offset in range(0, 5001, 100):
                    params = {"first": offset, "max": 100}
                    if config.created_after is not None:
                        params["createdAfter"] = config.created_after
                    result = await self._request("GET", path, params=params, is_list=True)
                    users.extend(result["data"])
                    if len(users) > 5000:
                        raise ValueError("Keycloak poll exceeds 5,000 users; narrow Created After before monitoring")
                    if len(result["data"]) < 100:
                        break
                fresh = await self._filter_unseen(users, lambda row: row.get("id") if isinstance(row.get("id"), str) and row.get("id") else None)
                return {"status": "success", "realm": credential.realm, "users": _redact(fresh, credential.access_token), "new_user_count": len(fresh)}
            method, route, query_fields, body_fields, is_list, statuses = ROUTES[config.operation]
            values = config.model_dump(exclude_none=True)
            path = route.format(realm=quote(credential.realm, safe=""), **{key: quote(str(value), safe="") for key, value in values.items()})
            params = {WIRE_NAMES.get(key, key): values[key] for key in query_fields if key in values}
            body = {WIRE_NAMES.get(key, key): values[key] for key in body_fields if key in values} if body_fields else None
            if "roles" in body_fields:
                body = values["roles"]
            result = await self._request(method, path, params=params, body=body, is_list=is_list, statuses=statuses)
            if "first" in query_fields:
                more = len(result["data"]) == config.max
                result.update(has_more=more, next_offset=config.first + len(result["data"]) if more else None)
            return {"status": "success", "action": config.operation, **_redact(result, credential.access_token)}
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "Keycloak transport failed; the outcome may be unknown. No automatic retry was made."}

    @classmethod
    def resolve_agent_event(cls, output):
        users = output.get("users", [])
        if not users:
            return None
        realm = output.get("realm", "")
        return {"title": "New Keycloak users", "text": f"New users in Keycloak realm {realm}: " + json.dumps(users, ensure_ascii=False)[:24000], "conversation_key": None}

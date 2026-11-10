"""Microsoft Entra ID users, groups and tenant inventory through Graph v1.0.

Uses the existing Microsoft delegated OAuth flow. Each action sends exactly one
documented request; collection continuations stay on the same Graph resource.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft_entra_id import ENTRA_SCOPES

GRAPH = "https://graph.microsoft.com/v1.0"


class EntraOAuthCredential(BaseModel):
    """Shared Microsoft sign-in with directory permissions and refresh support."""
    credential_type: Literal["microsoft_oauth"] = Field("microsoft_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1)
    refresh_token: str
    expires_at: str
    email: str
    model_config = ConfigDict(title="Microsoft Entra ID OAuth", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "microsoft",
        "x-oauth-scopes": list(ENTRA_SCOPES.declared_scopes()),
        "x-credential-instructions": "Connect a work or school Microsoft account. Directory permissions require administrator consent. Your Entra role must also permit each action; personal Microsoft accounts are not supported. Use cloud-managed users and security groups or Microsoft 365 groups. Role-assignable groups require additional permissions and are not supported.",
        "x-credential-url": "https://learn.microsoft.com/en-us/graph/auth/auth-concepts",
    })


@dataclass(frozen=True)
class Operation:
    title: str
    category: str
    method: str
    path: str
    fields: tuple[str, ...] = ()
    body: str = ""
    collection: bool = False
    paging: bool = False


OPERATIONS = {
    "get_me": Operation("Get My Profile", "Account", "GET", "/me"),
    "list_users": Operation("List Users", "User", "GET", "/users", collection=True, paging=True),
    "get_user": Operation("Get User", "User", "GET", "/users/{user_id}", ("user_id",)),
    "create_user": Operation("Create User", "User", "POST", "/users", ("display_name", "mail_nickname", "user_principal_name", "password", "account_enabled", "on_premises_immutable_id"), "user_create"),
    "update_user": Operation("Update User", "User", "PATCH", "/users/{user_id}", ("user_id", "display_name_update", "job_title", "department", "usage_location", "account_enabled_update"), "user_update"),
    "delete_user": Operation("Delete User", "User", "DELETE", "/users/{user_id}", ("user_id",)),
    "list_groups": Operation("List Groups", "Group", "GET", "/groups", collection=True, paging=True),
    "get_group": Operation("Get Group", "Group", "GET", "/groups/{group_id}", ("group_id",)),
    "create_group": Operation("Create Security Group", "Group", "POST", "/groups", ("display_name", "mail_nickname", "description"), "group_create"),
    "update_group": Operation("Update Group", "Group", "PATCH", "/groups/{group_id}", ("group_id", "display_name_update", "description_update"), "group_update"),
    "delete_group": Operation("Delete Group", "Group", "DELETE", "/groups/{group_id}", ("group_id",)),
    "list_group_members": Operation("List Group Members", "Membership", "GET", "/groups/{group_id}/members", ("group_id",), collection=True, paging=True),
    "add_group_user": Operation("Add User to Group", "Membership", "POST", "/groups/{group_id}/members/$ref", ("group_id", "user_id"), "reference"),
    "remove_group_member": Operation("Remove Group Member", "Membership", "DELETE", "/groups/{group_id}/members/{member_id}/$ref", ("group_id", "member_id")),
    "list_user_memberships": Operation("List User Memberships", "Membership", "GET", "/users/{user_id}/memberOf", ("user_id",), collection=True, paging=True),
    "list_applications": Operation("List App Registrations", "Application", "GET", "/applications", collection=True, paging=True),
    "list_service_principals": Operation("List Enterprise Applications", "Application", "GET", "/servicePrincipals", collection=True, paging=True),
    "list_organizations": Operation("Get Tenant Organizations", "Tenant", "GET", "/organization", collection=True),
    "list_subscribed_skus": Operation("List Subscribed Licenses", "Tenant", "GET", "/subscribedSkus", collection=True),
}


class OperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def validate_text(cls, value, info):
        if isinstance(value, str):
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use text without control characters")
            if info.field_name in {"user_id", "group_id", "member_id"}:
                if value in {".", ".."} or any(c in value for c in "/\\?#"):
                    raise ValueError("Use a single Graph object ID or user principal name")
        return value

    @model_validator(mode="after")
    def update_has_fields(self):
        if self.operation == "update_user" and all(getattr(self, k) is None for k in ("display_name_update", "job_title", "department", "usage_location", "account_enabled_update")):
            raise ValueError("Supply at least one user property to update")
        if self.operation == "update_group" and self.display_name_update is None and self.description_update is None:
            raise ValueError("Supply a group name or description")
        return self


FIELDS = {
    "user_id": (str, Field(..., min_length=1, max_length=320, title="User ID or Principal Name")),
    "group_id": (str, Field(..., min_length=1, max_length=128, title="Group ID")),
    "member_id": (str, Field(..., min_length=1, max_length=128, title="Member Object ID", description="Removes only membership via /$ref, never the directory object.")),
    "display_name": (str, Field(..., min_length=1, max_length=256, title="Display Name")),
    "mail_nickname": (str, Field(..., min_length=1, max_length=64, title="Mail Alias")),
    "user_principal_name": (str, Field(..., min_length=3, max_length=320, title="User Principal Name", description="Use a verified tenant domain, for example adelev@contoso.com.")),
    "password": (str, Field(..., min_length=8, max_length=256, title="Initial Password", repr=False, json_schema_extra={"ui:widget": "password", "writeOnly": True}, description="Must meet the tenant password policy. User must change it at next sign-in.")),
    "account_enabled": (bool, Field(True, title="Enable Account")),
    "on_premises_immutable_id": (str | None, Field(None, max_length=256, title="Immutable ID", description="Required when the principal name uses a federated domain.")),
    "description": (str | None, Field(None, max_length=1024, title="Description")),
    "display_name_update": (str | None, Field(None, min_length=1, max_length=256, title="Display Name")),
    "description_update": (str | None, Field(None, max_length=1024, title="Description")),
    "job_title": (str | None, Field(None, max_length=128, title="Job Title")),
    "department": (str | None, Field(None, max_length=64, title="Department")),
    "usage_location": (str | None, Field(None, min_length=2, max_length=2, pattern="^[A-Z]{2}$", title="Usage Country Code")),
    "account_enabled_update": (bool | None, Field(None, title="Enable Account")),
    "top": (int, Field(100, ge=1, le=100, title="Page Size")),
    "next_link": (str | None, Field(None, max_length=16384, title="Next Page Link", description="Paste next_link from the previous result of this same operation. The host and resource path must match.")),
}


def config_model(name, spec):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-category": spec.category, "x-display-name": spec.title, "x-is-trigger": False}))}
    fields.update({k: FIELDS[k] for k in spec.fields})
    if spec.paging:
        fields.update({k: FIELDS[k] for k in ("top", "next_link")})
    return create_model("Entra" + "".join(x.title() for x in name.split("_")) + "Config", __base__=OperationInput, **fields)


CONFIG_MODELS = {name: config_model(name, spec) for name, spec in OPERATIONS.items()}
EntraOperationConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class EntraNodeConfig(NodeConfig[EntraOperationConfig, EntraOAuthCredential]):
    pass


class MicrosoftEntraIdNode(WorkflowNode):
    integration_type = "automation-microsoft-entra-id"
    borrowed_credential_types = frozenset({"microsoft_oauth"})
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    scope_registry = ENTRA_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_me", noun="Microsoft account")

    @classmethod
    def get_config_model(cls):
        return EntraNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="microsoft")

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token
        if not isinstance(self.config, EntraNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Microsoft work or school account")
        credential = self.config.credentials
        credentials = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credentials, refresh=refresh_access_token,
            provider="microsoft", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            setattr(credential, key, credentials[key])
        op = self.config.config
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude={"operation"})
        path = spec.path
        for key in ("user_id", "group_id", "member_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values[key], safe=""))
        url = GRAPH + path
        params = {"$top": op.top} if spec.paging else None
        if spec.paging and op.next_link:
            parsed = urlsplit(op.next_link)
            if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or parsed.path != "/v1.0" + path or parsed.fragment:
                raise ValueError("Next page link must belong to this Graph resource")
            url, params = op.next_link, None
        body = self._body(spec.body, values)
        kwargs = {"headers": {"Authorization": "Bearer " + token, "Accept": "application/json"}, "params": params}
        if body is not None:
            kwargs["json"] = body
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(spec.method, url, **kwargs)
        if not 200 <= response.status_code < 300:
            try:
                error = response.json().get("error", {})
                message = error.get("message", "") if isinstance(error, dict) else str(error)
            except (ValueError, AttributeError):
                message = response.text[:500]
            raise ValueError(f"Microsoft Graph error ({response.status_code}): {message or response.reason_phrase}")
        result = {"status": "success", "operation": op.operation}
        if response.status_code == 204:
            result["acknowledged"] = True
            return result
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("Expected a Microsoft Graph JSON object")
        if spec.collection:
            if not isinstance(data.get("value"), list):
                raise ValueError("Expected a Microsoft Graph value collection")
            result.update(items=data["value"], count=len(data["value"]), next_link=data.get("@odata.nextLink"))
        else:
            data.pop("passwordProfile", None)
            result["data"] = data
        return result

    @staticmethod
    def _body(kind, v):
        if kind == "user_create":
            body = {"accountEnabled": v["account_enabled"], "displayName": v["display_name"],
                "mailNickname": v["mail_nickname"], "userPrincipalName": v["user_principal_name"],
                "passwordProfile": {"forceChangePasswordNextSignIn": True, "password": v["password"]}}
            if v.get("on_premises_immutable_id") is not None:
                body["onPremisesImmutableId"] = v["on_premises_immutable_id"]
            return body
        if kind == "group_create":
            return {"displayName": v["display_name"], "mailNickname": v["mail_nickname"],
                "mailEnabled": False, "securityEnabled": True, "groupTypes": [],
                **({"description": v["description"]} if v.get("description") is not None else {})}
        if kind in {"user_update", "group_update"}:
            names = {"display_name_update": "displayName", "description_update": "description",
                "job_title": "jobTitle", "department": "department", "usage_location": "usageLocation",
                "account_enabled_update": "accountEnabled"}
            return {target: v[key] for key, target in names.items() if v.get(key) is not None}
        if kind == "reference":
            return {"@odata.id": GRAPH + "/users/" + quote(v["user_id"], safe="")}
        return None

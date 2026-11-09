"""GoTo Connect calls, messages, voicemail, users and presence.

Each action makes one request to a fixed provider route. Pagination cursors and
provider response fields are preserved for subsequent workflow steps.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.go_to_connect_operations import OPERATIONS
from nodes.scopes.go_to_connect import GO_TO_CONNECT_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://api.goto.com"
Identifier = Annotated[str, Field(min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9_=-]+$")]
Phone = Annotated[str, Field(pattern=r"^\+[1-9][0-9]{1,14}$")]


class GoToConnectOAuthCredential(BaseModel):
    model_config = ConfigDict(title="GoTo Connect Account", hide_input_in_errors=True,
        json_schema_extra={"x-credential-type": "oauth", "x-oauth-provider": "go_to_connect",
            "x-oauth-scopes": GO_TO_CONNECT_SCOPES.declared_scopes(),
            "x-credential-url": "https://developer.logmeininc.com/clients",
            "x-credential-instructions": "Connect your GoTo Connect account. Enable the requested GoTo Connect scopes on your OAuth client. Listing account users requires super admin or configure PBX permission; other actions use the signed-in user's permissions."})
    credential_type: Literal["go_to_connect_oauth"] = Field("go_to_connect_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., max_length=4096, title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., max_length=4096, title="Refresh Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Expires At")
    scope: str | None = None
    _secrets = field_validator("access_token", "refresh_token", mode="before")(clean_secret)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("contactPhoneNumber", "userKey", check_fields=False)
    @classmethod
    def unique_query_values(cls, value):
        if isinstance(value, list) and len(value) != len(set(value)):
            raise ValueError("Query identifiers must be unique")
        return value


class CallFrom(_Closed):
    lineId: Identifier = Field(..., title="Calling Line ID")


class CallBody(_Closed):
    dialString: str = Field(..., min_length=1, max_length=100, title="Number to Dial")
    from_: CallFrom = Field(..., alias="from", title="Calling Line")
    autoAnswer: bool = Field(False, strict=True, title="Auto Answer", description="Automatically answer the initiating line where supported; requires intercom on the line.")
    phoneNumberId: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")] | None = Field(None, title="Caller ID Phone Number ID")


class MessageBody(_Closed):
    ownerPhoneNumber: Phone = Field(..., title="Sending Phone Number")
    contactPhoneNumbers: list[Phone] = Field(..., min_length=1, max_length=10, title="Recipient Phone Numbers")
    body: str = Field(..., max_length=1000, title="Message Text")
    userKey: Identifier | None = Field(None, title="Send on Behalf of User", description="Requires super admin permission; omit to send as yourself.")

    @field_validator("contactPhoneNumbers")
    @classmethod
    def unique_contacts(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Recipient phone numbers must be unique")
        return value


class VoicemailStatus(_Closed):
    name: Literal["status"] = "status"
    value: Literal["READ", "NEW"]


class PresenceBody(_Closed):
    userAppearance: Literal["NONE", "ONLINE", "OFFLINE", "AWAY", "BUSY"] | None = None
    userDoNotDisturb: Literal["NONE", "DO_NOT_DISTURB"] | None = None
    userDoNotDisturbExpiration: AwareDatetime | None = None
    userStatus: Literal["NONE", "IN_A_MEETING"] | None = Field(None, description="IN_A_MEETING expires after 60 seconds unless refreshed. NONE resets it.")
    userNote: str | None = Field(None, max_length=80, description="An empty string clears the note.")

    @model_validator(mode="after")
    def patch_fields(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Supply at least one presence field")
        if self.userDoNotDisturbExpiration is not None and self.userDoNotDisturb != "DO_NOT_DISTURB":
            raise ValueError("Set DO_NOT_DISTURB when providing its expiration")
        return self


BODY_MODELS = {"CallBody": CallBody, "MessageBody": MessageBody,
    "VoicemailStatus": list[VoicemailStatus], "PresenceBody": PresenceBody}


def _config(name, op):
    fields = {"operation": (Literal[name], Field(name, description=op["label"], json_schema_extra={
        "ui:hidden": True, "x-display-name": op["label"], "x-is-trigger": False,
        "x-operation-kind": "read" if op["method"] == "GET" else "write"}))}
    for key, location in op["params"].items():
        required = location == "path" or key == "ownerPhoneNumber" or (key == "contactPhoneNumber" and name != "list_conversations") or (key == "accountKey" and name in {"list_users", "list_voicemailboxes"}) or (key == "userKey" and name == "get_presence")
        kind = Identifier
        options = {}
        if key == "pageMarker":
            kind = Annotated[str, Field(min_length=1, max_length=8192)]
        elif key == "ownerPhoneNumber":
            kind = Phone
        elif key == "contactPhoneNumber":
            kind = Annotated[list[Phone], Field(min_length=1, max_length=10)]
        elif key == "userKey" and name == "get_presence":
            kind = Annotated[list[Identifier], Field(min_length=1, max_length=100)]
        elif key in {"oldestTimestamp", "newestTimestamp"}:
            kind = AwareDatetime
        elif key == "pageSize":
            kind = Annotated[int, Field(strict=True, ge=1, le=100)]
        elif key == "page":
            kind = Annotated[int, Field(strict=True, ge=0)]
        elif key in {"unreadOnly", "showArchived"}:
            kind = Annotated[bool, Field(strict=True)]
        elif key == "status":
            kind = Literal["NEW", "READ"]
        elif key == "sort":
            kind = Literal["+timestamp", "-timestamp"]
        if not required:
            kind = kind | None
        fields[key] = (kind, Field(... if required else None, title=re.sub(r"([a-z])([A-Z])", r"\1 \2", key).title(), **options))
    if op["body"]:
        fields["body"] = (BODY_MODELS[op["body"]], Field(..., title="Details", **({"min_length": 1} if name == "update_voicemail" else {})))
    # Restrict this action to the current user; the provider limits other-user writes to DND.
    if name == "set_my_presence":
        fields.pop("userKey", None)
    return create_model("GoToConnect" + "".join(s.title() for s in name.split("_")) + "Config", __base__=_Closed, __module__=__name__, **fields)


CONFIG_MODELS = {name: _config(name, op) for name, op in OPERATIONS.items()}
globals().update({cls.__name__: cls for cls in CONFIG_MODELS.values()})
GoToConnectConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class GoToConnectNodeConfig(NodeConfig[GoToConnectConfig, GoToConnectOAuthCredential]):
    pass


class GoToConnectNode(WorkflowNode):
    integration_type = "automation-go-to-connect"
    scope_registry = GO_TO_CONNECT_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_my_setup", noun="GoTo Connect accounts", label_keys=("accountKey",))

    @classmethod
    def get_config_model(cls):
        return GoToConnectNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.go_to_connect_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="go_to_connect")

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a GoTo Connect account")
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.go_to_connect_oauth import refresh_access_token
        credential = self.config.credentials.model_dump()
        await ensure_fresh_oauth_token(credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            credential=credential, refresh=refresh_access_token, provider="go_to_connect", caller_path="execute")
        config = self.config.config
        data = config.model_dump(mode="json", by_alias=True, exclude_none=True)
        op = OPERATIONS[config.operation]
        path = op["path"]
        params = []
        for key, location in op["params"].items():
            if key not in data:
                continue
            value = data[key]
            if location == "path":
                path = path.replace("{" + key + "}", quote(value, safe=""))
            else:
                for item in value if isinstance(value, list) else [value]:
                    params.append((key, str(item).lower() if type(item) is bool else str(item)))
        kwargs = {"json": data["body"]} if op["body"] else {}
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(op["method"], BASE + path, params=params,
                headers={"Authorization": "Bearer " + credential["access_token"], "Accept": "application/json"}, **kwargs)
        response.raise_for_status()
        if response.status_code == 204:
            result = None
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("GoTo Connect response exceeds 10 MB")
            result = response.json()
            if not isinstance(result, (dict, list)):
                raise ValueError("Expected a GoTo Connect JSON object or collection")
            if isinstance(result, dict) and result.get("errorCode"):
                raise ValueError(str(result.get("message") or result["errorCode"]))
        return {"status": "success", "operation": config.operation, "data": result}

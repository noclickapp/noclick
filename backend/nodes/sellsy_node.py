"""Sellsy CRM operations against the provider's published API v2 contract.

Each operation sends exactly one documented API request. Lists return one page
and preserve the provider's pagination (including opaque offset strings).
https://docs.sellsy.com/api/v2/
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.sellsy import SELLSY_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://api.sellsy.com/v2"


class SellsyOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Sellsy Account", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "sellsy",
        "x-oauth-scopes": sorted(SELLSY_SCOPES.declared_scopes()),
        "x-credential-url": "https://www.sellsy.fr/developer/api-v2",
        "x-credential-instructions": "Connect your Sellsy account with OAuth. To connect by hand, paste an existing access token and refresh token from your Sellsy API V2 access. Request read and write access to companies, contacts, individuals and opportunities, and read access to staffs. Access tokens expire; NoClick refreshes them using the configured Sellsy OAuth app.",
    })
    credential_type: Literal["sellsy_oauth"] = Field("sellsy_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", min_length=1, json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes")
    name: Optional[str] = Field(None, title="Account Name")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Sellsy token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def update_has_fields(self):
        if getattr(self, "operation", "").startswith("update_"):
            body = self.model_dump(exclude_none=True, exclude={"operation", "id"})
            if not body:
                raise ValueError("Supply at least one field to update")
        related = getattr(self, "related", None)
        if related is not None and sum(row.type in ("company", "individual") for row in related) != 1:
            raise ValueError("Relate the opportunity to exactly one company or individual")
        return self


class SellsyRelatedRecord(_Input):
    id: int = Field(..., ge=1)
    type: Literal["company", "individual", "contact"]


_Id = Annotated[int, Field(ge=1)]
_Name = Annotated[str, Field(min_length=1, max_length=200)]
_Type = Literal["prospect", "client", "supplier"]
_COMMON = {
    "email": (Optional[EmailStr], None),
    "phone_number": (Optional[Annotated[str, Field(max_length=50)]], None),
    "mobile_number": (Optional[Annotated[str, Field(max_length=50)]], None),
    "website": (Optional[AnyHttpUrl], None),
    "note": (Optional[str], None),
    "owner_id": (Optional[_Id], None),
    "is_archived": (Optional[bool], None),
}
_PEOPLE = {**_COMMON, "first_name": (Optional[_Name], None), "last_name": (Optional[_Name], None),
           "position": (Optional[_Name], None), "civility": (Optional[Literal["mr", "mrs", "ms"]], None)}
_COMPANY = {**_COMMON, "name": (Optional[Annotated[str, Field(min_length=1, max_length=250)]], None),
            "reference": (Optional[Annotated[str, Field(max_length=100)]], None)}
_OPPORTUNITY = {
    "name": (Optional[str], None), "pipeline": (Optional[_Id], None), "step": (Optional[_Id], None),
    "amount": (Optional[str], None), "probability": (Optional[Annotated[int, Field(ge=0, le=100)]], None),
    "status": (Optional[Literal["open", "won", "lost", "cancelled", "closed", "late"]], None),
    "due_date": (Optional[date], None), "note": (Optional[str], None), "owner_id": (Optional[_Id], None),
    "contact_ids": (Optional[list[_Id]], None), "assigned_staff_ids": (Optional[list[_Id]], None),
    "related": (Optional[Annotated[list[SellsyRelatedRecord], Field(min_length=1)]], None),
}
_LIST = {
    "limit": (Annotated[int, Field(ge=1, le=100)], 25),
    "offset": (Union[Annotated[int, Field(ge=0)], str], Field(0, description="Use the pagination offset returned by Sellsy; may be an opaque string.")),
    "direction": (Literal["asc", "desc"], "asc"),
}

# name -> method, path, body-field names. No arbitrary URL or method inputs.
OPERATIONS = {}
_models = []
for _plural, _singular, _fields in (("companies", "company", _COMPANY), ("contacts", "contact", _PEOPLE),
                                     ("individuals", "individual", _PEOPLE), ("opportunities", "opportunity", _OPPORTUNITY)):
    for _verb, _method in (("list", "GET"), ("get", "GET"), ("create", "POST"), ("update", "PUT")):
        _name = f"{_verb}_{_plural if _verb == 'list' else _singular}"
        _path = f"/{_plural}" + ("/{id}" if _verb in ("get", "update") else "")
        _config = dict(_LIST) if _verb == "list" else ({"id": (_Id, ...)} if _verb in ("get", "update") else {})
        _body_fields = dict(_fields) if _verb in ("create", "update") else {}
        if _verb == "create":
            if _singular in ("company", "individual"):
                _body_fields["type"] = (_Type, ...)
            _required = {"company": ("name",), "contact": ("last_name",), "individual": ("last_name",),
                         "opportunity": ("name", "pipeline", "step", "related") }[_singular]
            for _key in _required:
                _required_type = {"pipeline": _Id, "step": _Id,
                                  "related": Annotated[list[SellsyRelatedRecord], Field(min_length=1)],
                                  "name": Annotated[str, Field(min_length=1, max_length=250)] if _singular == "company" else _Name,
                                  "last_name": _Name}[_key]
                _body_fields[_key] = (_required_type, ...)
        _config.update(_body_fields)
        _config["operation"] = (Literal[_name], Field(_name, json_schema_extra={"ui:hidden": True}))
        _model = create_model("Sellsy" + "".join(x.title() for x in _name.split("_")) + "Config", __base__=_Input, **_config)
        globals()[_model.__name__] = _model
        _models.append(_model)
        OPERATIONS[_name] = (_method, _path, tuple(_body_fields))


class SellsyGetMeConfig(_Input):
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


_models.append(SellsyGetMeConfig)
OPERATIONS["get_me"] = ("GET", "/staffs/me", ())
SellsyConfig = Annotated[Union[tuple(_models)], Field(discriminator="operation")]


class SellsyFullConfig(NodeConfig[SellsyConfig, SellsyOAuthCredential]):
    pass


def _guard_credential(config_data):
    raw = config_data.get("credentials")
    if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != "sellsy_oauth":
        raise ValueError("Attach a Sellsy account credential")


class SellsyNode(WorkflowNode):
    integration_type = "automation-sellsy"
    scope_registry = SELLSY_SCOPES
    connection_evidence = ConnectionEvidence(noun="Sellsy companies", operation="list_companies", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return SellsyFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _guard_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _guard_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.sellsy_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="sellsy",
        )

    async def execute(self, inputs):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.sellsy_oauth import refresh_access_token
        if not isinstance(self.config, SellsyFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Sellsy account")
        credential = self.config.credentials
        auth = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=auth, refresh=refresh_access_token, provider="sellsy", caller_path="execute",
        )
        for key in ("access_token", "refresh_token", "expires_at", "scope"):
            if key in auth:
                setattr(credential, key, auth[key])
        config = self.config.config
        operation = config.operation
        method, path, fields = OPERATIONS[operation]
        if "{id}" in path:
            path = path.replace("{id}", str(config.id))
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation", "id"})
        query = values if operation.startswith("list_") else None
        body = {key: values[key] for key in fields if key in values} if fields else None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=query, json=body,
                    headers={"Authorization": f"Bearer {credential.access_token}", "Accept": "application/json"})
        except httpx.RequestError:
            return {"status": "error", "error": "Sellsy could not be reached"}
        if response.status_code not in ({200} if method == "GET" else {200, 201, 204}):
            message = "Sellsy request was rejected"
            if "json" in response.headers.get("content-type", "").lower():
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        if isinstance(error.get("error"), dict):
                            error = error["error"]
                        detail = error.get("message") or error.get("error_description") or error.get("error")
                        if isinstance(detail, str):
                            message = detail[:1000]
                            for secret in (credential.access_token, credential.refresh_token):
                                message = message.replace(secret, "[redacted]")
                except ValueError:
                    pass
            return {"status": "error", "status_code": response.status_code, "error": message}
        if response.status_code == 204:
            return {"status": "success", "status_code": 204, "data": None}
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
            return {"status": "error", "error": "Sellsy returned an unexpected response"}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "error": "Sellsy returned invalid JSON"}
        if not isinstance(payload, dict) or "error" in payload:
            return {"status": "error", "error": "Sellsy returned an unexpected response"}
        if operation.startswith("list_"):
            if not isinstance(payload.get("data"), list) or not isinstance(payload.get("pagination"), dict):
                return {"status": "error", "error": "Sellsy returned an unexpected page"}
            return {"status": "success", "data": payload["data"], "pagination": payload["pagination"]}
        # Only the identity probe needs a recognizable account. Other resource
        # schemas do not require an id, so preserve their documented JSON shape.
        if operation == "get_me" and (not isinstance(payload.get("id"), int) or not isinstance(payload.get("email"), str)):
            return {"status": "error", "error": "Sellsy returned an unexpected record"}
        return {"status": "success", "data": payload}

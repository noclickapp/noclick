"""Spiro CRM API v1: https://developers.spiro.ai/api/docs/v1/openapi.json.

Each operation sends one REST request, with no automatic write retries.
"""
from datetime import datetime
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
    field_validator,
    model_validator,
)
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.spiro_oauth import OAUTH_PROVIDER
from nodes.scopes.spiro import SPIRO_SCOPES
from nodes.spiro_operations import OPERATIONS
from utils.ssrf import guarded_async_client


class SpiroOAuthCredential(BaseModel):
    model_config = ConfigDict(
        title="Spiro Account",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "spiro",
            "x-oauth-scopes": sorted(SPIRO_SCOPES.declared_scopes()),
            "x-credential-url": "https://support.spiro.ai/article/76-using-spiros-api",
            "x-credential-instructions": "Connect Spiro with an API authorization created in Settings > Integrations > Spiro API. Spiro requires organization-wide admin access. For manual connection paste your issued access and refresh tokens; token refresh requires the instance's Spiro OAuth app credentials.",
        },
    )
    credential_type: Literal["spiro_oauth"] = Field(
        "spiro_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: Optional[str] = Field(None, title="Token Expiry")

    @field_validator("access_token", "refresh_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Spiro token")
        if len(value) > 4096 or any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


def _text(required=False, maximum=10000):
    return (
        str if required else Optional[str],
        Field(... if required else None, min_length=1, max_length=maximum),
    )


def _id(required=True):
    return (
        int if required else Optional[int],
        Field(... if required else None, ge=1, le=2147483647),
    )


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator(
        "interacted_at", "remind_me_at", "done_at", "close_at", check_fields=False
    )
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError("Use an ISO 8601 timestamp with timezone") from None
        return value

    @model_validator(mode="after")
    def nonempty_update(self):
        if self.operation.startswith("update_") and not any(
            v is not None
            for k, v in self.model_dump().items()
            if k not in {"operation", "id"}
        ):
            raise ValueError("Provide at least one field to update")
        return self


def _config(name, method, path, kind):
    fields = {
        "operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True}))
    }
    for key in ("id", "pipeline_id"):
        if "{" + key + "}" in path:
            fields[key] = _id()
    if name.startswith("list_") and kind != "opportunity_stage":
        fields.update(
            page_number=(int, Field(1, ge=1, le=1000000)),
            page_size=(int, Field(50, ge=1, le=100)),
            sort=_text(maximum=200),
        )
        filters = {
            "company": {"name": str, "phone": str, "user_id": int},
            "contact": {
                "email": str,
                "first_name": str,
                "last_name": str,
                "company_id": int,
                "opportunity_id": int,
                "campaign_id": int,
            },
            "opportunity": {
                "company_id": int,
                "contact_id": int,
                "opened": bool,
                "won": bool,
            },
            "note": {"contact_id": int},
            "activity": {"contact_id": int},
            "reminder": {
                "contact_id": int,
                "company_id": int,
                "opportunity_id": int,
                "user_id": int,
            },
        }
        for key, typ in filters.get(kind, {}).items():
            fields["filter_" + key] = (
                _id(False)
                if typ is int
                else _text(maximum=500)
                if typ is str
                else (Optional[bool], None)
            )
    if method in {"POST", "PUT"}:
        creating = method == "POST"
        if kind == "company":
            fields.update(
                {
                    key: _text(creating and key == "name")
                    for key in (
                        "name",
                        "website",
                        "city",
                        "zipcode",
                        "country",
                        "state",
                        "phone",
                        "address",
                        "description",
                    )
                }
            )
        elif kind == "contact":
            fields.update(
                {
                    key: _text(creating and key in {"first_name", "last_name"})
                    for key in (
                        "first_name",
                        "last_name",
                        "email",
                        "title",
                        "phone",
                        "mobile_phone",
                        "home_phone",
                        "description",
                    )
                }
            )
        elif kind == "opportunity":
            fields.update(
                name=_text(creating),
                amount=(Optional[float], Field(None, ge=0, allow_inf_nan=False)),
                close_at=_text(),
                description=_text(),
            )
            for key in ("company_id", "pipeline_id", "opportunity_stage_id"):
                fields[key] = _id(creating)
        elif kind in {"note", "activity"}:
            fields.update(
                subject=_text(creating),
                description=_text(creating, 100000),
                interacted_at=_text(),
            )
            if creating:
                fields.update(
                    owner_type=(Literal["contact", "company", "opportunity"], ...),
                    owner_id=_id(),
                )
            if kind == "activity":
                fields.update(
                    disposition=_text(maximum=100),
                    call_duration=(Optional[int], Field(None, ge=0, le=2147483647)),
                )
        elif kind == "reminder":
            fields.update(
                reason=_text(creating),
                remind_me_at=_text(creating),
                remind_me=(Optional[bool], None),
                done_at=_text(),
            )
            if creating:
                fields.update(
                    owner_type=(Literal["contact", "company", "opportunity"], ...),
                    owner_id=_id(),
                )
        fields["custom"] = (
            Optional[dict[str, Union[str, int, float, bool, None]]],
            Field(
                None, description="Custom field names and values configured in Spiro."
            ),
        )
        fields["user_id"] = _id(False)
        if kind == "contact":
            fields["company_id"] = _id(False)
    return create_model(
        "Spiro" + "".join(s.title() for s in name.split("_")) + "Config",
        __base__=_Input,
        __module__=__name__,
        **fields
    )


CONFIG_MODELS = {name: _config(name, *route) for name, route in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
SpiroConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")
]


class SpiroNodeConfig(NodeConfig[SpiroConfig, SpiroOAuthCredential]):
    pass


class SpiroNode(WorkflowNode):
    integration_type = "automation-spiro"
    scope_registry = SPIRO_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_users",
        noun="organization members",
        label_keys=("email", "first_name", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return SpiroNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        from nodes.core.oauth_refresh import freshen_oauth_credential

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=OAUTH_PROVIDER.refresh,
            provider="spiro",
        )

    @staticmethod
    def _body(op, kind):
        values = op.model_dump(exclude_none=True)
        attrs = {
            k: v
            for k, v in values.items()
            if k
            not in {
                "operation",
                "id",
                "owner_type",
                "owner_id",
                "user_id",
                "company_id",
                "pipeline_id",
                "opportunity_stage_id",
            }
        }
        relations = {}
        for key in ("user", "company", "pipeline", "opportunity_stage"):
            identifier = values.get(key + "_id")
            if identifier is not None:
                relations[key] = {"data": {"type": key, "id": str(identifier)}}
        if "owner_type" in values:
            key = values["owner_type"] if kind == "reminder" else "owner"
            relations[key] = {
                "data": {"type": values["owner_type"], "id": str(values["owner_id"])}
            }
        return {
            "data": {
                "attributes": attrs,
                **({"relationships": relations} if relations else {}),
            }
        }

    @staticmethod
    def _records(payload, kind, *, listing, expected_id=None):
        if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
            raise ValueError("Spiro returned an error or invalid JSON:API document")
        data = payload.get("data")
        rows = data if listing else [data]
        if not isinstance(rows, list):
            raise ValueError("Spiro resource list is missing")
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("type") != kind
                or not isinstance(row.get("id"), str)
                or not row["id"].isascii()
                or not row["id"].isdigit()
                or int(row["id"]) <= 0
                or not isinstance(row.get("attributes"), dict)
            ):
                raise ValueError("Spiro returned an invalid resource")
        if len({r["id"] for r in rows}) != len(rows):
            raise ValueError("Spiro repeated a resource ID")
        if expected_id is not None and data["id"] != str(expected_id):
            raise ValueError("Spiro returned a different resource")
        return data

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Spiro account")
        op = self.config.config
        method, path, kind = OPERATIONS[op.operation]
        path = path.format(**op.model_dump())
        credential = self.config.credentials.model_dump()
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token

        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=credential,
            refresh=OAUTH_PROVIDER.refresh,
            provider="spiro",
            caller_path="execute",
        )
        params = {}
        if op.operation.startswith("list_") and hasattr(op, "page_number"):
            params = {"page[number]": op.page_number, "page[size]": op.page_size}
            if op.sort is not None:
                params["sort"] = op.sort
            for key, value in op.model_dump(exclude_none=True).items():
                if key.startswith("filter_"):
                    params["filter[" + key[7:] + "]"] = (
                        int(value) if isinstance(value, bool) else value
                    )
        writing = method != "GET"
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    "https://api.spiro.ai" + path,
                    params=params,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Accept": "application/vnd.api+json",
                        "Content-Type": "application/vnd.api+json",
                    },
                    **({"json": self._body(op, kind)} if writing else {})
                )
        except httpx.HTTPError:
            return {
                "status": "error",
                "error": "Spiro request did not complete",
                **({"write_outcome": "unknown"} if writing else {}),
            }
        if not 200 <= response.status_code < 300:
            detail = response.text[:2000].replace(token, "[redacted]")
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": detail or "Spiro rejected the request",
                **(
                    {"write_outcome": "unknown"}
                    if writing and response.status_code >= 500
                    else {}
                ),
            }
        try:
            if len(response.content) > 5000000 or response.headers.get(
                "content-type", ""
            ).split(";", 1)[0].lower() not in {
                "application/json",
                "application/vnd.api+json",
            }:
                raise ValueError("Spiro returned invalid JSON media")
            payload = response.json()
            listing = op.operation.startswith("list_")
            data = self._records(
                payload, kind, listing=listing, expected_id=getattr(op, "id", None)
            )
            result = {
                "status": "success",
                "data": data,
                "http_status": response.status_code,
            }
            if listing:
                result["items"] = [
                    {**row["attributes"], "id": row["id"], "type": row["type"]}
                    for row in data
                ]
                pagination = payload.get("meta", {}).get("pagination", {})
                if not isinstance(pagination, dict):
                    raise ValueError("Spiro returned invalid pagination")
                following = pagination.get("next_page")
                if following is not None and (
                    type(following) is not int
                    or not getattr(op, "page_number", 1) < following <= 1000000
                ):
                    raise ValueError("Spiro pagination did not advance")
                result.update(
                    pagination=pagination,
                    next_page=following,
                    has_more=following is not None,
                )
            if writing:
                result["write_acknowledged"] = True
            return result
        except (ValueError, TypeError, KeyError, AttributeError):
            return {
                "status": "error",
                "error": "Spiro response could not be verified",
                **({"write_outcome": "unknown"} if writing else {}),
            }

"""Pinterest v5 workflow node, generated from Pinterest's public OpenAPI catalog.

The operation descriptors include the documented request schemas. Paths are
fixed by the operation catalog; users supply only documented parameters and bodies.
"""

import json
import logging
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, BeforeValidator, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, freshen_oauth_credential
from nodes.oauth.pinterest_oauth import refresh_access_token
from nodes.scopes.pinterest import PINTEREST_SCOPES, granted_scopes
from nodes.pinterest_operations import OPERATIONS

logger = logging.getLogger(__name__)
PINTEREST_API_BASE = "https://api.pinterest.com/v5"


class PinterestOAuthCredential(BaseModel):
    credential_type: Literal["pinterest_oauth"] = Field(
        "pinterest_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    scope: Optional[str] = Field(None, title="Granted Scopes")
    username: Optional[str] = Field(None, title="Pinterest Username")

    model_config = ConfigDict(
        title="Pinterest OAuth",
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "pinterest",
            "x-oauth-scopes": sorted(PINTEREST_SCOPES.declared_scopes()),
        }
    )


class PinterestAccessTokenCredential(BaseModel):
    """Short-lived test token issued by Pinterest's developer console."""

    credential_type: Literal["pinterest_access_token"] = Field(
        "pinterest_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", json_schema_extra={"ui:widget": "password"}
    )

    scope: Optional[str] = Field(
        None,
        title="Granted Scopes",
        description="Scopes granted to this token. MSOT beta tokens must include msot:write.",
    )

    model_config = ConfigDict(
        title="Pinterest Access Token",
        json_schema_extra={"x-credential-url": "https://developers.pinterest.com/apps/"}
    )


def _array_values(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _enforce_granted_scopes(name, scopes):
    requirement = PINTEREST_SCOPES.require(name)
    if not set(requirement.scopes) <= set(scopes):
        raise ValueError(requirement.note or "Required Pinterest scopes are missing")


def _make_config(name: str, descriptor: Dict[str, Any]) -> type[BaseModel]:
    fields: Dict[str, Any] = {
        "operation": (
            Literal[name],
            Field(
                name,
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": descriptor["category"],
                    "x-display-name": descriptor["label"],
                    "x-is-trigger": False,
                },
            ),
        )
    }
    for parameter in descriptor["params"]:
        key = parameter["name"]
        if key in fields:
            raise ValueError(f"Duplicate Pinterest parameter in {name}: {key}")
        kind = parameter["type"]
        value_type = {"integer": int, "number": float, "boolean": bool, "object": dict}.get(kind, str)
        if kind == "array":
            # Keep comma-separated form inputs while publishing the API's array shape.
            item_schema = parameter["schema"].get("items", {})
            item_type = {"integer": int, "number": float, "boolean": bool}.get(item_schema.get("type"), str)
            item_type = Annotated[item_type, Field(json_schema_extra=item_schema)]
            value_type = Annotated[list[item_type], BeforeValidator(_array_values)]
        required = parameter["required"]
        annotation = value_type if required else Optional[value_type]
        extra: Dict[str, Any] = dict(parameter["schema"])
        description = (
            parameter["description"] or f"Pinterest {parameter['in']} parameter"
        )
        if kind == "array":
            description += " (comma-separated values)"
        fields[key] = (
            annotation,
            Field(
                ... if required else None,
                title=key.replace("_", " ").title(),
                description=description,
                json_schema_extra=extra,
            ),
        )
    if descriptor["has_body"]:
        fields["body_json"] = (
            str if descriptor["body_required"] else Optional[str],
            Field(
                ... if descriptor["body_required"] else None,
                title="Request Body (JSON)",
                description="JSON object or array matching Pinterest's request body for this operation.",
                json_schema_extra={
                    "ui:widget": "textarea",
                    "contentMediaType": "application/json",
                    "contentSchema": descriptor["body_schema"],
                },
            ),
        )
    class_name = (
        "Pinterest" + "".join(piece.title() for piece in name.split("_")) + "Config"
    )
    requirement = PINTEREST_SCOPES.require(name)
    model_config = ConfigDict(
        json_schema_extra=(
            {
                "x-requires-tier": requirement.tier,
                "x-tier-label": "Pinterest MSOT beta",
                "x-required-scopes": list(requirement.scopes),
            }
            if not requirement.is_standard
            else {}
        )
    )
    return create_model(
        class_name,
        __config__=model_config,
        __module__=__name__,
        __doc__=descriptor["description"],
        **fields,
    )


_CONFIG_MODELS = tuple(_make_config(name, spec) for name, spec in OPERATIONS.items())
PinterestConfig = Annotated[Union[_CONFIG_MODELS], Discriminator("operation")]
PinterestCredential = Union[PinterestOAuthCredential, PinterestAccessTokenCredential]


class PinterestNodeConfig(NodeConfig[PinterestConfig, PinterestCredential]):
    pass


class PinterestNode(WorkflowNode):
    """Pinterest pins, boards, account, ads, catalog, and business API actions."""

    integration_type = "automation-pinterest"
    credential_provider_labels = {"pinterest": "Pinterest"}
    scope_registry = PINTEREST_SCOPES

    edit_examples = [
        "List my Pinterest boards",
        "Create a Pin on my recipe board",
        "Get analytics for a Pin",
        "List Pinterest ad accounts",
    ]
    connection_evidence = ConnectionEvidence(
        operation="user_account_get", noun="account"
    )

    @classmethod
    def get_config_model(cls):
        return PinterestNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name, credential_data, context=None, page_token=None, search=None
    ):
        if field_name != "restricted_operations":
            return []
        options = []
        for name in cls.scope_registry.elevated():
            try:
                _enforce_granted_scopes(
                    name, granted_scopes(credential_data)
                )
            except ValueError:
                continue
            options.append({"value": name, "label": OPERATIONS[name]["label"]})
        return options

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        if credential_data.get("credential_type") != "pinterest_oauth":
            return credential_data
        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="pinterest",
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not isinstance(config, PinterestNodeConfig):
            raise ValueError("Valid Pinterest configuration is required")
        credential = config.credentials
        if not credential:
            raise ValueError("Connect a Pinterest account or add a test access token")
        name = config.config.operation
        requirement = self.scope_registry.require(name)
        if not requirement.is_standard:
            _enforce_granted_scopes(
                name, granted_scopes(credential.model_dump())
            )
        if isinstance(credential, PinterestOAuthCredential):
            cred_dict = credential.model_dump()
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=refresh_access_token,
                provider="pinterest",
            )
            credential.access_token = cred_dict["access_token"]
            credential.refresh_token = cred_dict.get("refresh_token")
            credential.expires_at = cred_dict.get("expires_at")

        op = config.config
        name = op.operation
        spec = OPERATIONS[name]
        values = op.model_dump(exclude_none=True)
        path = spec["path"]
        query: Dict[str, Any] = {}
        for param in spec["params"]:
            key = param["name"]
            value = values.get(key)
            if value in (None, ""):
                continue
            if param["in"] == "path":
                path = path.replace("{" + key + "}", quote(str(value), safe=""))
            else:
                if isinstance(value, list):
                    query[key] = value if param["explode"] else ",".join(str(item) for item in value)
                elif isinstance(value, dict):
                    # Catalog diagnostics supplies its report selector as one
                    # JSON object in the named `parameters` query field.
                    query[key] = json.dumps(value, separators=(",", ":"))
                else:
                    query[key] = value
        if "{" in path or "}" in path:
            raise ValueError("A required Pinterest path parameter is missing")
        body = None
        if spec["has_body"] and values.get("body_json") is not None:
            try:
                body = json.loads(values["body_json"])
            except json.JSONDecodeError as exc:
                raise ValueError("Request Body must be valid JSON") from exc
            if not isinstance(body, (dict, list)):
                raise ValueError("Request Body must be a JSON object or array")
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                spec["method"],
                f"{PINTEREST_API_BASE}{path}",
                headers={
                    "Authorization": f"Bearer {credential.access_token}",
                    "Accept": "application/json",
                },
                params=query or None,
                json=body,
            )
        duration = round((time.monotonic() - started) * 1000, 2)
        try:
            data: Any = response.json() if response.content else {}
        except ValueError:
            data = {"raw": response.text}
        if response.status_code >= 400:
            message = (
                data.get("message") or data.get("error")
                if isinstance(data, dict)
                else str(data)
            )
            return {
                "status": "error",
                "action": name,
                "error": str(message),
                "status_code": response.status_code,
                "timing_ms": {"api_request": duration},
            }
        return {
            "status": "success",
            "action": name,
            "data": data,
            "status_code": response.status_code,
            "timing_ms": {"api_request": duration},
        }

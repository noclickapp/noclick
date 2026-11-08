"""Kommo CRM workflow node for the documented JSON API v4 endpoints.

The operation catalog records each official reference page. Kommo writes are
usually bulk arrays, while single-record updates use objects; the JSON body
field accepts either and is sent without transformation.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client, normalize_provider_subdomain
from nodes.kommo_operations import KOMMO_OPERATIONS
from nodes.scopes.kommo import KOMMO_SCOPES
from nodes.oauth.kommo_oauth import OAUTH_PROVIDER

logger = logging.getLogger(__name__)

_ENTITY_TYPES = {"leads", "contacts", "companies"}


class KommoOAuthCredential(BaseModel):
    credential_type: Literal["kommo_oauth"] = Field(
        "kommo_oauth", json_schema_extra={"ui:hidden": True}
    )
    referer: str = Field(
        ..., title="Kommo account host", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access token")
    refresh_token: str = Field(..., title="Refresh token")
    expires_at: str = Field(..., title="Token expiry")

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Kommo OAuth",
            "x-credential-type": "oauth",
            "x-oauth-scopes": KOMMO_SCOPES.declared_scopes(),
            "x-oauth-provider": "kommo",
            "x-credential-url": "https://developers.kommo.com/docs/oauth-20",
        }
    )


class KommoLongLivedTokenCredential(BaseModel):
    credential_type: Literal["kommo_long_lived_token"] = Field(
        "kommo_long_lived_token", json_schema_extra={"ui:hidden": True}
    )
    subdomain: str = Field(
        ..., title="Kommo account subdomain", description="The part before .kommo.com"
    )
    token: str = Field(
        ..., title="Long-lived token", json_schema_extra={"ui:widget": "password"}
    )

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Kommo Long-lived Token",
            "x-credential-url": "https://developers.kommo.com/docs/long-lived-token",
            "x-credential-instructions": "Create a private integration in Kommo Settings > Integrations and copy its long-lived token.",
        }
    )


KommoCredential = Union[KommoOAuthCredential, KommoLongLivedTokenCredential]


def _operation_model(spec: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, Any] = {
        "operation": (
            Literal[spec["operation"]],
            Field(
                spec["operation"],
                title=spec["title"],
                json_schema_extra={
                    "const": spec["operation"],
                    "ui:hidden": True,
                    "x-category": spec["category"],
                    "x-display-name": spec["title"],
                },
            ),
        )
    }
    for name in spec["path_parameters"]:
        if name == "entity_type":
            fields[name] = (
                Literal["leads", "contacts", "companies"],
                Field(..., title="Entity type"),
            )
        else:
            fields[name] = (str, Field(..., title=name.replace("_", " ").title()))
    fields["query"] = (
        Optional[str],
        Field(
            None,
            title="Query parameters (JSON)",
            description='Optional JSON object; use literal Kommo filter keys such as {"filter[is_completed]": 1}.',
            json_schema_extra={"ui:widget": "textarea"},
        ),
    )
    if spec["has_body"]:
        fields["body"] = (
            str,
            Field(
                ...,
                title="JSON body",
                description="JSON object or array matching the linked Kommo API reference.",
                json_schema_extra={"ui:widget": "textarea"},
            ),
        )
    return create_model(
        "Kommo"
        + "".join(word.capitalize() for word in spec["operation"].split("_"))
        + "Config",
        __doc__=spec["title"],
        **fields,
    )


KOMMO_CONFIGS = {
    name: _operation_model(spec) for name, spec in KOMMO_OPERATIONS.items()
}
KommoConfig = Annotated[
    Union[tuple(KOMMO_CONFIGS.values())], Field(discriminator="operation")
]


class KommoNodeConfig(NodeConfig[KommoConfig, KommoCredential]):
    """Kommo operation and account credential."""


def _parse_json(raw: Optional[str], field: str, *, object_only: bool = False) -> Any:
    if raw is None or raw == "":
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Kommo {field} must be valid JSON") from exc
    if object_only and not isinstance(value, dict):
        raise ValueError(f"Kommo {field} must be a JSON object")
    if not object_only and not isinstance(value, (dict, list)):
        raise ValueError(f"Kommo {field} must be a JSON object or array")
    return value


class KommoNode(WorkflowNode):
    """Run Kommo CRM actions against one verified account host."""

    integration_type = "automation-kommo"
    scope_registry = KOMMO_SCOPES
    credential_provider_labels = {"kommo": "Kommo Account"}

    edit_examples = [
        "List new Kommo leads",
        "Add a contact to Kommo",
        "Move a lead to another pipeline stage",
        "Create a follow-up task in Kommo",
    ]
    connection_evidence = ConnectionEvidence(operation="get_account", noun="account")

    @classmethod
    def get_config_model(cls):
        return KommoNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        if credential_data.get("credential_type") != "kommo_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="kommo",
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.monotonic()
        if not self.config or not isinstance(self.config, KommoNodeConfig):
            raise ValueError("Kommo configuration is required")
        credentials = self.config.credentials
        if not credentials:
            raise ValueError("Kommo credentials are required")
        if isinstance(credentials, KommoOAuthCredential):
            host = OAUTH_PROVIDER.validate_context({"referer": credentials.referer})[
                "referer"
            ]
        else:
            subdomain = normalize_provider_subdomain(
                credentials.subdomain, "kommo.com", field_name="Kommo subdomain"
            )
            host = f"{subdomain}.kommo.com"
        spec = KOMMO_OPERATIONS[self.config.config.operation]
        values = self.config.config.model_dump(exclude_none=True)
        path = spec["path"]
        for name in spec["path_parameters"]:
            value = str(values[name])
            if name == "entity_type" and value not in _ENTITY_TYPES:
                raise ValueError("Kommo entity type is unsupported")
            if not value:
                raise ValueError(f"Kommo {name} is required")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        if re.search(r"{[^}]+}", path):
            raise ValueError("A Kommo path parameter is missing")
        query = _parse_json(values.get("query"), "query", object_only=True)
        body = _parse_json(values.get("body"), "body")
        if spec["has_body"] and body is None:
            raise ValueError("Kommo JSON body is required")
        if isinstance(credentials, KommoOAuthCredential):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token

            cred_dict = credentials.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=OAUTH_PROVIDER.bind_refresh(cred_dict),
                additional_token_fields=OAUTH_PROVIDER.credential_fields,
                provider="kommo",
            )
            credentials.access_token = cred_dict["access_token"]
            credentials.expires_at = cred_dict.get("expires_at")
            if cred_dict.get("refresh_token"):
                credentials.refresh_token = cred_dict["refresh_token"]
        else:
            token = credentials.token
        url = f"https://{host}/api/v4{path}"
        try:
            async with guarded_async_client(timeout=30) as client:
                response = await client.request(
                    spec["method"],
                    url,
                    params=query,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/hal+json",
                    },
                )
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                payload = {"text": response.text}
            result = {
                "status": "error" if response.is_error else "success",
                "action": self.config.config.operation,
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }
            if response.is_error:
                result.update(status_code=response.status_code, error=payload)
            else:
                result["data"] = payload
            return result
        except httpx.HTTPError:
            logger.warning("Kommo request failed for %s", self.config.config.operation)
            return {
                "status": "error",
                "action": self.config.config.operation,
                "status_code": 502,
                "error": "Kommo request failed",
                "timing_ms": {
                    "api_request": round((time.monotonic() - started) * 1000, 2)
                },
            }

"""Clover merchant platform actions, generated from the official Platform API reference."""

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.clover_operations import CLOVER_OPERATIONS as OPERATIONS, CLOVER_TRIGGERS
from nodes.scopes.clover import CLOVER_SCOPES
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


REGION_API_BASES = {
    "sandbox": "https://apisandbox.dev.clover.com",
    "north_america": "https://api.clover.com",
    "europe": "https://api.eu.clover.com",
    "latin_america": "https://api.la.clover.com",
}
Region = Literal["sandbox", "north_america", "europe", "latin_america"]


class CloverAPIKeyCredential(BaseModel):
    credential_type: Literal["clover_api_token"] = Field(
        "clover_api_token", json_schema_extra={"ui:hidden": True}
    )
    merchant_id: str = Field(..., title="Merchant ID")
    api_token: str = Field(
        ..., title="API token", json_schema_extra={"ui:widget": "password"}
    )
    region: Region = Field("sandbox", title="Clover region")

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Clover API Token",
            "x-credential-url": "https://www.clover.com/developers",
            "x-credential-instructions": "Use a Clover sandbox merchant API token, or a merchant access token issued for your own Clover app. Choose the matching region.",
        }
    )


class CloverOAuthCredential(BaseModel):
    credential_type: Literal["clover_oauth"] = Field(
        "clover_oauth", json_schema_extra={"ui:hidden": True}
    )
    merchant_id: str = Field(..., title="Merchant ID")
    access_token: str = Field(..., json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    clover_domain: Literal["clover.com", "eu.clover.com", "la.clover.com"] = Field(
        "clover.com", title="Clover Region",
        description="clover.com for North America, eu.clover.com for Europe, la.clover.com for Latin America.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "title": "Clover OAuth",
            "x-credential-type": "oauth",
            "x-oauth-provider": "clover",
            "x-oauth-scopes": CLOVER_SCOPES.declared_scopes(),
            "x-credential-url": "https://www.clover.com/developers",
        }
    )


CloverCredential = Union[CloverAPIKeyCredential, CloverOAuthCredential]


def _field_name(name: str, prefix: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()


def _make_config(name: str, op: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for variable in re.findall(r"\{([^}]+)\}", op["path"]):
        if variable != "mId":
            fields[_field_name(variable, "path")] = (
                str,
                Field(
                    ..., title=variable, description=f"Clover {variable} from the API."
                ),
            )
    for param in op["params"]:
        if param["in"] != "query":
            continue
        fields[_field_name(param["name"], "query")] = (
            str if param["required"] else Optional[str],
            Field(
                ... if param["required"] else None,
                title=param["name"],
                description=param["description"],
            ),
        )
    if op["body"]:
        fields["body_json"] = (
            str if op["method"] in {"POST", "PUT", "PATCH"} else Optional[str],
            Field(
                ... if op["method"] in {"POST", "PUT", "PATCH"} else None,
                title="Request body JSON",
                description="JSON object accepted by this Clover endpoint.",
                json_schema_extra={
                    "ui:widget": "code_editor",
                    "x-code-language": "json",
                },
            ),
        )
    return create_model(
        "Clover" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(
            Literal[name],
            Field(
                name,
                title=op["label"],
                description=op["description"],
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": op["category"],
                    "x-is-trigger": False,
                    "x-display-name": op["label"],
                },
            ),
        ),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
def _make_poll_config(name: str, plural: str) -> type[BaseModel]:
    return create_model(
        "Clover" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=PollTriggerConfigBase, __module__=__name__,
        operation=(Literal[name], Field(name, title=f"On New or Updated {plural}",
            json_schema_extra={"const": name, "ui:hidden": True, "x-category": "Triggers",
                "x-is-trigger": True, "x-display-name": f"On New or Updated {plural}"})),
        lookback_minutes=(int, Field(60, ge=1, le=129600, title="Lookback Minutes",
            description="Check changes within this window; choose a window longer than the polling interval (maximum 90 days).")),
    )


POLL_MODELS = {name: _make_poll_config(name, plural) for name, (_, plural) in CLOVER_TRIGGERS.items()}
globals().update({model.__name__: model for model in POLL_MODELS.values()})
CloverConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values()) + tuple(POLL_MODELS.values())], Discriminator("operation")
]


class CloverNodeConfig(NodeConfig[CloverConfig, CloverCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object")
    return value


class CloverNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-clover"
    credential_provider_labels = {"clover": "Clover Account"}
    scope_registry = CLOVER_SCOPES
    connection_evidence = ConnectionEvidence(
        identity_operation="get_merchant", noun="Clover merchant"
    )
    edit_examples = [
        "List my Clover inventory items",
        "Create a Clover customer",
        "Find recent Clover orders",
        "Check a Clover item's stock",
    ]

    @classmethod
    def get_config_model(cls):
        return CloverNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        if (
            not credential_data
            or credential_data.get("credential_type") != "clover_oauth"
        ):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.clover_oauth import OAUTH_PROVIDER

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            provider="clover",
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
        )

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, CloverNodeConfig):
            raise ValueError("Clover configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Clover credentials")
        if isinstance(credential, CloverOAuthCredential):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.clover_oauth import OAUTH_PROVIDER

            cred_dict = credential.model_dump()
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=OAUTH_PROVIDER.bind_refresh(cred_dict),
                provider="clover",
                additional_token_fields=OAUTH_PROVIDER.credential_fields,
                caller_path="execute",
            )
            credential.access_token = cred_dict["access_token"]
            credential.refresh_token = cred_dict["refresh_token"]
            credential.expires_at = cred_dict.get("expires_at")
            credential.clover_domain = cred_dict["clover_domain"]

        config = self.config.config
        self.scope_registry.require(config.operation)
        if config.operation in CLOVER_TRIGGERS:
            return await self._poll_changes(credential, config)
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op["path"]
        for variable in re.findall(r"\{([^}]+)\}", path):
            value = (
                credential.merchant_id
                if variable == "mId"
                else values.pop(_field_name(variable, "path"))
            )
            if not value:
                raise ValueError(f"Clover {variable} is required")
            path = path.replace("{" + variable + "}", quote(str(value), safe=""))
        params = {}
        for param in op["params"]:
            if param["in"] == "query":
                value = values.pop(_field_name(param["name"], "query"), None)
                if value is not None:
                    params[param["name"]] = value
        body = values.pop("body_json", None)
        request = {"json": _json_object(body)} if body is not None else {}
        started = time.perf_counter()
        response = await self._request(credential, op["method"], path, params=params or None, **request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.content:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text[:1000]}
        else:
            data = {"ok": True}
        if isinstance(data, list):
            data = {"items": [item if isinstance(item, dict) else {"value": item} for item in data]}
        return {"status": "success", "operation": config.operation,
                "status_code": response.status_code, "data": data,
                "timing_ms": {"api_request": elapsed_ms}}

    @staticmethod
    def _api_base(credential: CloverCredential) -> str:
        if isinstance(credential, CloverAPIKeyCredential):
            return REGION_API_BASES[credential.region]
        # The credential enum is an exact provider-host allowlist.
        return "https://api." + credential.clover_domain

    async def _request(self, credential: CloverCredential, method: str, path: str, **kwargs) -> httpx.Response:
        token = credential.api_token if isinstance(credential, CloverAPIKeyCredential) else credential.access_token
        base = self._api_base(credential)
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                method, base + path,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                         "User-Agent": "NoClick/1.0 (Clover integration)"},
                **kwargs,
            )
        if response.is_error or response.is_redirect:
            raise ValueError(f"Clover API error {response.status_code}: {response.text[:350]}")
        return response

    async def _poll_changes(self, credential: CloverCredential, config: BaseModel) -> dict[str, Any]:
        # Official filtering and pagination: /dev/docs/applying-filters and /paginating-elements.
        resource, _ = CLOVER_TRIGGERS[config.operation]
        since = int(time.time() * 1000) - config.lookback_minutes * 60000
        path = f"/v3/merchants/{quote(credential.merchant_id, safe='')}/{resource}"
        records = []
        for page in range(100):
            response = await self._request(credential, "GET", path,
                params={"filter": f"modifiedTime>={since}", "limit": 100, "offset": page * 100})
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
                raise ValueError("Clover collection response must contain an elements array")
            elements = data["elements"]
            for item in elements:
                if (not isinstance(item, dict) or not item.get("id")
                        or not isinstance(item.get("modifiedTime"), int)):
                    raise ValueError("Clover changed records must include id and modifiedTime")
            records.extend(elements)
            if len(elements) < 100:
                break
        else:
            raise ValueError("Clover poll exceeds 10,000 records; reduce Lookback Minutes")
        fresh = await self._filter_unseen(records, lambda item: f"{item['id']}:{item['modifiedTime']}")
        return {"status": "success", "operation": config.operation,
                "merchant_id": credential.merchant_id, "resource": resource,
                "records": fresh, "changed_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output: dict[str, Any], config: dict[str, Any]) -> bool:
        if config.get("operation") in CLOVER_TRIGGERS:
            return bool(output.get("changed_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]) -> Optional[dict[str, Any]]:
        if output.get("operation") not in CLOVER_TRIGGERS:
            return super().resolve_agent_event(output)
        records = output.get("records", [])
        if not records:
            return None
        merchant = output.get("merchant_id")
        lines = []
        for item in records[:10]:
            if output.get("resource") == "orders":
                customers = item.get("customers") or []
                if isinstance(customers, dict):
                    customers = customers.get("elements", [])
                customer_ids = [c.get("id") for c in customers if isinstance(c, dict)]
                content = f"{item.get('title') or 'Order'}; state {item.get('state', 'unknown')}; total {item.get('total')} {item.get('currency', '')}; customers {customer_ids}"
            else:
                content = f"{item.get('name') or 'Inventory item'}; price {item.get('price')}; available {item.get('available')}"
            lines.append(f"- {content}; id {item['id']}; modified {item['modifiedTime']}")
        return {"text": f"Clover merchant {merchant}: {len(records)} new or updated {output.get('resource')}:\n" + "\n".join(lines),
                "conversation_key": f"clover:{merchant}"}

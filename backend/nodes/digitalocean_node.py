"""DigitalOcean API v2 actions generated from the official OpenAPI specification."""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.digitalocean_operations import OPERATIONS
from nodes.scopes.digitalocean import DIGITALOCEAN_SCOPES
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

OAUTH_SCOPES = DIGITALOCEAN_SCOPES.declared_scopes()
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class DigitalOceanOAuthCredential(BaseModel):
    credential_type: Literal["digitalocean_oauth"] = Field(
        "digitalocean_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")

    model_config = ConfigDict(json_schema_extra={
        "title": "DigitalOcean OAuth", "x-credential-type": "oauth", "x-oauth-provider": "digitalocean",
        "x-oauth-scopes": OAUTH_SCOPES,
        "x-credential-url": "https://docs.digitalocean.com/reference/api/oauth/",
    })


class DigitalOceanPersonalAccessTokenCredential(BaseModel):
    credential_type: Literal["digitalocean_pat"] = Field(
        "digitalocean_pat", json_schema_extra={"ui:hidden": True})
    token: str = Field(..., title="Personal Access Token", json_schema_extra={"ui:widget": "password"})

    model_config = ConfigDict(json_schema_extra={
        "title": "DigitalOcean Personal Access Token",
        "x-credential-type": "api_key",
        "x-credential-url": "https://docs.digitalocean.com/reference/api/create-personal-access-token/",
    })


DigitalOceanCredential = Union[DigitalOceanOAuthCredential, DigitalOceanPersonalAccessTokenCredential]


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"],
            description=op["description"] + " See " + op["docs_url"],
            json_schema_extra={"const": name, "ui:hidden": True,
                               "x-category": op["category"], "x-display-name": op["label"],
                               "x-is-trigger": False},
        )),
    }
    for prefix, params in (("path", op["path_params"]), ("query", op["query_params"]),
                           ("header", op["header_params"])):
        for param in params:
            fields[_field_name(prefix, param["name"])] = (
                str if param["required"] else Optional[str],
                Field(... if param["required"] else None,
                      title=param["name"].replace("_", " ").title(),
                      description=param["description"][:500]),
            )
    if op["body_json"]:
        body_desc = "JSON request body. See " + op["docs_url"]
        if op["body_required_fields"]:
            body_desc += " Required top-level keys: " + ", ".join(op["body_required_fields"]) + "."
        fields["body_json"] = (
            str if op["body_required"] else Optional[str],
            Field(... if op["body_required"] else None, title="Request Body (JSON)",
                  description=body_desc, json_schema_extra=_JSON_EDITOR),
        )
    return create_model(
        "DigitalOcean" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class DigitalOceanOnNewAlertConfig(PollTriggerConfigBase):
    operation: Literal["on_new_alert"] = Field("on_new_alert", title="On New Alert", json_schema_extra={
        "const": "on_new_alert", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Alert",
    })
    rule_id: Optional[str] = Field(None, title="Alert Rule ID")
    resource_urn: Optional[str] = Field(None, title="Resource URN")


DigitalOceanConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (DigitalOceanOnNewAlertConfig,)],
                               Discriminator("operation")]


class DigitalOceanNodeConfig(NodeConfig[DigitalOceanConfig, DigitalOceanCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Request Body must contain valid JSON") from exc
    if not isinstance(value, (dict, list)):
        raise ValueError("Request Body must be a JSON object or array")
    return value


def _query_value(raw: str, kind: str) -> Any:
    if kind in {"array", "object"}:
        try:
            value = json.loads(raw)
        except ValueError:
            return raw
        if kind == "array" and isinstance(value, list):
            # OpenAPI form+explode query arrays are repeated keys. httpx
            # serializes a list this way (e.g. ?event_types=a&event_types=b).
            return [str(item) for item in value]
        return value
    return raw


class DigitalOceanNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Run stable DigitalOcean API v2 actions with OAuth or a personal token."""

    integration_type = "automation-digitalocean"
    credential_provider_labels = {"digitalocean": "DigitalOcean Account"}
    connection_evidence = ConnectionEvidence(operation="get_account", noun="account")
    scope_registry = DIGITALOCEAN_SCOPES
    edit_examples = [
        "List DigitalOcean Droplets", "Create a DigitalOcean domain record",
        "List DigitalOcean databases", "Get the current DigitalOcean account",
    ]

    @classmethod
    def get_config_model(cls):
        return DigitalOceanNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.digitalocean_oauth import refresh_access_token

        if not credential_data or not credential_data.get("refresh_token"):
            return credential_data

        async def refresh(token: str):
            return await refresh_access_token(token)

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh, provider="digitalocean",
        )

    async def _ensure_fresh_token(self, credentials: DigitalOceanCredential) -> None:
        if not isinstance(credentials, DigitalOceanOAuthCredential):
            return
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.digitalocean_oauth import refresh_access_token

        async def refresh(token: str):
            return await refresh_access_token(token)

        credential = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credential, refresh=refresh,
            provider="digitalocean",
        )
        credentials.access_token = credential["access_token"]
        credentials.expires_at = credential.get("expires_at")
        if credential.get("refresh_token"):
            credentials.refresh_token = credential["refresh_token"]

    @staticmethod
    async def _request(credentials: DigitalOceanCredential, name: str,
                       values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        path = op["path"]
        for param in op["path_params"]:
            raw = param["name"]
            value = values.pop(_field_name("path", raw), None)
            if value is None or str(value).strip() in {"", ".", ".."}:
                raise ValueError(f"{raw} is required")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = {}
        for param in op["query_params"]:
            raw = param["name"]
            value = values.pop(_field_name("query", raw), None)
            if value is not None and value != "":
                params[raw] = _query_value(value, param["type"])
        token = (credentials.access_token if isinstance(credentials, DigitalOceanOAuthCredential)
                 else credentials.token)
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        for param in op["header_params"]:
            raw = param["name"]
            value = values.pop(_field_name("header", raw), None)
            if value is not None and value != "":
                headers[raw] = value
        options: dict[str, Any] = {}
        if op["body_json"]:
            body = _parse_json(values.pop("body_json", None))
            if op["body_required"] and body is None:
                raise ValueError("Request Body is required")
            if isinstance(body, dict):
                missing = [key for key in op["body_required_fields"] if key not in body]
                if missing:
                    raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
            if body is not None:
                options["json"] = body
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(
                op["method"], "https://api.digitalocean.com" + path,
                headers=headers, params=params or None, **options,
            )
        try:
            data: Any = response.json() if response.content else {}
        except ValueError:
            data = {"text": response.text[:20000]}
        if response.is_error or response.is_redirect:
            message = (data.get("message") or data.get("id")) if isinstance(data, dict) else None
            raise ValueError(f"DigitalOcean API error {response.status_code}: {message or 'request failed'}")
        return {"status": "success", "operation": name, "status_code": response.status_code,
                "data": data, "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)}}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_alert":
            return bool(output.get("new_alert_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        alerts = output.get("alert_instances") if isinstance(output, dict) else None
        if not isinstance(alerts, list):
            return super().resolve_agent_event(output)
        if not alerts:
            return None
        lines = [
            f"- {alert['severity']} alert on {alert.get('resource_urn') or 'account signal'}: "
            f"value {alert['value']}, status {alert['status']}, fired {alert['triggered_at']} "
            f"(alert {alert['id']}, rule {alert['rule_id']})"
            for alert in alerts[:10]
        ]
        return {"text": f"DigitalOcean: {len(alerts)} new alert(s) in your account:\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_alerts(self, credentials, config):
        # The pinned contract orders these append-only records by triggered_at
        # descending. Fetch numbered pages without following response URLs.
        alerts = []
        for page in range(1, 51):
            params = {"query_page": str(page), "query_per_page": "200"}
            if config.rule_id:
                params["query_rule_id"] = config.rule_id
            if config.resource_urn:
                params["query_resource_urn"] = config.resource_urn
            data = (await self._request(credentials, "insights_list_alert_instances", params))["data"]
            if not isinstance(data, dict) or not isinstance(data.get("alert_instances"), list):
                raise ValueError("DigitalOcean alert list response is missing alert_instances")
            rows = data["alert_instances"]
            for row in rows:
                if not isinstance(row, dict) or any(key not in row for key in
                        ("id", "rule_id", "severity", "status", "value", "triggered_at")):
                    raise ValueError("DigitalOcean returned an invalid alert instance")
            alerts.extend(rows)
            if not data.get("links", {}).get("pages", {}).get("next"):
                break
        else:
            raise ValueError("Too many DigitalOcean alerts; choose an alert rule or resource to monitor")
        fresh = await self._filter_unseen(alerts, lambda alert: str(alert["id"]))
        return {"status": "success", "operation": "on_new_alert", "alert_instances": fresh,
                "new_alert_count": len(fresh)}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, DigitalOceanNodeConfig) or not self.config.credentials:
            raise ValueError("Connect DigitalOcean with OAuth or a Personal Access Token")
        credentials = self.config.credentials
        await self._ensure_fresh_token(credentials)
        config = self.config.config
        if isinstance(config, DigitalOceanOnNewAlertConfig):
            return await self._poll_alerts(credentials, config)
        return await self._request(credentials, config.operation,
                                   config.model_dump(exclude={"operation"}, exclude_none=True))

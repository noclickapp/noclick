"""Canopy Connect API 1.0.0: fixed team-scoped reads and writes.

Contract: https://docs.usecanopy.com/openapi/documentation.json
Authentication: https://docs.usecanopy.com/reference/authentication-guide
List operations return one provider page; pass the documented cursor/offset explicitly.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from uuid import UUID
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.usecanopy.com/api/v1.0.0"


class CanopyConnectCredential(BaseModel):
    model_config = ConfigDict(title="Canopy Connect API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.usecanopy.com/dashboard/settings/api-settings",
            "x-credential-instructions": "In Canopy Connect, open Settings → API and copy your Team ID, Client ID and Client Secret. Choose a key matching your sandbox or production links. NoClick sends the Client ID and Client Secret using HTTP Basic authentication. The team read verifies access; individual operations may require additional plan permissions.",
        })
    credential_type: Literal["canopy_connect_api_key"] = Field("canopy_connect_api_key", json_schema_extra={"ui:hidden": True})
    canopy_team_id: UUID = Field(..., title="Team ID")
    client_id: str = Field(..., min_length=1, title="Client ID", json_schema_extra={"ui:widget": "password"})
    client_secret: str = Field(..., min_length=1, title="Client Secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("client_id", "client_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value) or (info.field_name == "client_id" and ":" in value):
            raise ValueError("Paste the API credential without spaces or a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", regex_engine="python-re")


class CanopyGetTeamConfig(_Input):
    """Get team. See https://docs.usecanopy.com/reference/get-team."""
    operation: Literal["get_team"] = Field("get_team", json_schema_extra={"ui:hidden": True})


class CanopyListPullsConfig(_Input):
    """List pulls. See https://docs.usecanopy.com/reference/get-pulls."""
    operation: Literal["list_pulls"] = Field("list_pulls", json_schema_extra={"ui:hidden": True})
    since: Optional[datetime] = Field(None, description='Filter by Pulls that occurred since the supplied date (inclusive)')
    before: Optional[datetime] = Field(None, description='Filter by Pulls that occurred before the supplied date (inclusive)')
    limit: int = Field(10, description='Optionally limit the number of Pulls that are returned in the response to a maximum of limit. Use along with offset', ge=1, le=100)
    offset: Optional[int] = Field(None, description='Optionally return Pulls starting from the supplied offset within the total list of Pulls matching the query. Use along with limit', ge=0)


class CanopyGetPullConfig(_Input):
    """Get pull. See https://docs.usecanopy.com/reference/get-pull-by-id."""
    operation: Literal["get_pull"] = Field("get_pull", json_schema_extra={"ui:hidden": True})
    pullId: UUID = Field(..., description='ID of Pull to return')


class CanopyUpdatePullConfig(_Input):
    """Update pull. See https://docs.usecanopy.com/reference/patch-pull-by-id."""
    operation: Literal["update_pull"] = Field("update_pull", json_schema_extra={"ui:hidden": True})
    pullId: UUID = Field(..., description='ID of Pull to return')
    is_archived: bool = Field(..., description='Whether the pull is archived')


class CanopyCheckPullPolicyConfig(_Input):
    """Check pull policy. See https://docs.usecanopy.com/reference/post-pull-policy-check."""
    operation: Literal["check_pull_policy"] = Field("check_pull_policy", json_schema_extra={"ui:hidden": True})
    pullId: UUID = Field(..., description='ID of Pull that Document belongs to')


class CanopyListWebhooksConfig(_Input):
    """List webhooks. See https://docs.usecanopy.com/reference/get-webhooks."""
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"ui:hidden": True})


class CanopyCreateWebhookConfig(_Input):
    """Create webhook. See https://docs.usecanopy.com/reference/post-webhooks."""
    operation: Literal["create_webhook"] = Field("create_webhook", json_schema_extra={"ui:hidden": True})
    hookUrl: str = Field(..., description='The URL that the webhook requests will go to', pattern="^https?://[^ /]+")
    eventTypes: list[Literal['COMPLETE', 'POLICIES_AVAILABLE', 'POLICY_AVAILABLE', 'AUTH_STATUS', 'SERVICING_STATUS_UPDATED', 'VALIDATION_COMPLETE']] = Field(..., description='The event types that will trigger the webhook request')


class CanopyUpdateWebhookConfig(_Input):
    """Update webhook. See https://docs.usecanopy.com/reference/patch-webhook."""
    operation: Literal["update_webhook"] = Field("update_webhook", json_schema_extra={"ui:hidden": True})
    webhookId: UUID = Field(..., description='ID of Webhook')
    isActive: Optional[bool] = Field(None, description='Whether your webhook is active and will receive webhook requests')
    eventTypes: Optional[list[Literal['COMPLETE', 'POLICIES_AVAILABLE', 'POLICY_AVAILABLE', 'AUTH_STATUS', 'SERVICING_STATUS_UPDATED', 'VALIDATION_COMPLETE']]] = Field(None, description='The event types that will trigger the webhook request')

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None or key == "on_success_redirect_url" and key in self.model_fields_set
                   for key in type(self).model_fields if key not in {'operation', 'webhookId'}):
            raise ValueError("Provide at least one field to update")
        return self


class CanopyDeleteWebhookConfig(_Input):
    """Delete webhook. See https://docs.usecanopy.com/reference/delete-webhook."""
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"ui:hidden": True})
    webhookId: UUID = Field(..., description='ID of Webhook')


class CanopyListMonitoringsConfig(_Input):
    """List monitorings. See https://docs.usecanopy.com/reference/get-monitorings."""
    operation: Literal["list_monitorings"] = Field("list_monitorings", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, description='Pagination limit', ge=1, le=100)
    before: Optional[UUID] = Field(None, description='Pagination before pointer of a monitoring_id')
    pull_id: Optional[UUID] = Field(None, description='Filter used to list Monitorings related to a Pull (cannot be used with account_identifier)')
    account_identifier: Optional[str] = Field(None, description='Filter used to list Monitorings related to an Account Identifier (cannot be used with pull_id)')
    status: Optional[Literal['ACTIVE', 'STOPPED']] = Field(None, description='Filter used to list Monitorings of a certain status')

    @model_validator(mode="after")
    def filters(self):
        if self.pull_id is not None and self.account_identifier is not None:
            raise ValueError("Use pull_id or account_identifier, not both")
        return self


class CanopyCreateMonitoringConfig(_Input):
    """Create monitoring. See https://docs.usecanopy.com/reference/post-monitoring."""
    operation: Literal["create_monitoring"] = Field("create_monitoring", json_schema_extra={"ui:hidden": True})
    interval: str = Field(..., examples=["P1M"], description='How often the information should be refreshed. Must be >= 30 days. We accept ISO-8601 duration interval value and support days, months, and/or years.', pattern='^(-?)P(?=\\d|T\\d)(?:(\\d+)Y)?(?:(\\d+)M)?(?:(\\d+)([DW]))?(?:T(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+(?:\\.\\d+)?)S)?)?$')
    next_pull_date: Optional[datetime] = Field(None, description='Optional date the next refresh should occur (Can be used as a start date). Must be >= 30 days after the Pull was created. Defaults to Pull created date + interval.')
    stop_after_date: Optional[datetime] = Field(None, description='Optional date after which monitoring should stop')
    pull_id: UUID = Field(..., description='ID of the Pull to be monitored')


class CanopyGetMonitoringConfig(_Input):
    """Get monitoring. See https://docs.usecanopy.com/reference/get-monitoring."""
    operation: Literal["get_monitoring"] = Field("get_monitoring", json_schema_extra={"ui:hidden": True})
    monitoringId: UUID = Field(..., description='ID of Monitoring')
    with_pulls: Optional[Literal[True]] = Field(None, description='Whether pulls should be included')
    limit: str = Field('100', description='Pagination limit for the pulls')
    before: Optional[UUID] = Field(None, description='Pagination before pointer for a pull_id')


class CanopyUpdateMonitoringConfig(_Input):
    """Update monitoring. See https://docs.usecanopy.com/reference/patch-monitoring."""
    operation: Literal["update_monitoring"] = Field("update_monitoring", json_schema_extra={"ui:hidden": True})
    monitoringId: UUID = Field(..., description='ID of Monitoring')
    interval: Optional[str] = Field(None, examples=["P1M"], description='How often the information should be refreshed. Must be >= 30 days. We accept ISO-8601 duration interval value and support days, months, and/or years.', pattern='^(-?)P(?=\\d|T\\d)(?:(\\d+)Y)?(?:(\\d+)M)?(?:(\\d+)([DW]))?(?:T(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+(?:\\.\\d+)?)S)?)?$')
    next_pull_date: Optional[datetime] = Field(None, description='Optional date the next refresh should occur. Must be >= 30 days after the latest Pull was created. Defaults to Pull created date + interval.')
    stop_after_date: Optional[datetime] = Field(None, description='Optional date after which monitoring should stop')
    status: Optional[str] = Field(None, description='Optional status to update the monitoring to')

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None or key == "on_success_redirect_url" and key in self.model_fields_set
                   for key in type(self).model_fields if key not in {'monitoringId', 'operation'}):
            raise ValueError("Provide at least one field to update")
        return self


class CanopyDeleteMonitoringConfig(_Input):
    """Delete monitoring. See https://docs.usecanopy.com/reference/delete-monitoring."""
    operation: Literal["delete_monitoring"] = Field("delete_monitoring", json_schema_extra={"ui:hidden": True})
    monitoringId: UUID = Field(..., description='ID of Monitoring')


class CanopyListWidgetsConfig(_Input):
    """List widgets. See https://docs.usecanopy.com/reference/get-widgets."""
    operation: Literal["list_widgets"] = Field("list_widgets", json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, description='Pagination limit for the widgets', ge=1, le=100)
    before: Optional[UUID] = Field(None, description='Pagination before pointer for a widget_id')


class CanopyCreateWidgetConfig(_Input):
    """Create widget. See https://docs.usecanopy.com/reference/post-widgets."""
    operation: Literal["create_widget"] = Field("create_widget", json_schema_extra={"ui:hidden": True})
    intro_title: Optional[str] = Field(None, description='The message displayed upon the introduction of the Widget flow.')
    public_alias: Optional[str] = Field(None, description='The public identifier for the Widget (eg. demo => https://app.usecanopy.com/c/demo). When not explicitly set, a public_alias will be auto generated.')
    company_name: Optional[str] = Field(None, description='The company name presented in the Widget flow.')
    brand_color_hex: Optional[str] = Field(None, description='RRGGBB hexadecimal string used for color theming in the Widget flow.', pattern="^[0-9a-fA-F]{6}$")
    success_message: Optional[str] = Field(None, description='The message displayed upon successful completion of the Widget flow.')
    on_success_redirect_url: Optional[str] = Field(None, description='The URL the user is taken to upon successful completion of the Widget flow.')
    cobranded_intro_screen: Optional[bool] = Field(None, description='Whether the enhanced “cobranded” introduction screen is enabled for the Widget flow.')
    agents: Optional[list[UUID]] = Field(None, description='Optional list of agents to update (either list of agent_ids or agent object with agent_id)')


class CanopyGetWidgetConfig(_Input):
    """Get widget. See https://docs.usecanopy.com/reference/get-widgetId."""
    operation: Literal["get_widget"] = Field("get_widget", json_schema_extra={"ui:hidden": True})
    widgetId: UUID = Field(..., description='widgetId')


class CanopyUpdateWidgetConfig(_Input):
    """Update widget. See https://docs.usecanopy.com/reference/patch-widgetId."""
    operation: Literal["update_widget"] = Field("update_widget", json_schema_extra={"ui:hidden": True})
    widgetId: UUID = Field(..., description='widgetId')
    intro_title: Optional[str] = Field(None, description='The message displayed upon the introduction of the Widget flow.')
    public_alias: Optional[str] = Field(None, description='The public identifier for the Widget (eg. demo => https://app.usecanopy.com/c/demo). When not explicitly set, a public_alias will be auto generated.')
    company_name: Optional[str] = Field(None, description='The company name presented in the Widget flow.')
    brand_color_hex: Optional[str] = Field(None, description='RRGGBB hexadecimal string used for color theming in the Widget flow.', pattern="^[0-9a-fA-F]{6}$")
    success_message: Optional[str] = Field(None, description='The message displayed upon successful completion of the Widget flow.')
    on_success_redirect_url: Optional[str] = Field(None, description='The URL the user is taken to upon successful completion of the Widget flow.')
    cobranded_intro_screen: Optional[bool] = Field(None, description='Whether the enhanced “cobranded” introduction screen is enabled for the Widget flow.')
    agents: Optional[list[UUID]] = Field(None, description='Optional list of agents to update (either list of agent_ids or agent object with agent_id)')

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None or key == "on_success_redirect_url" and key in self.model_fields_set
                   for key in type(self).model_fields if key not in {'operation', 'widgetId'}):
            raise ValueError("Provide at least one field to update")
        return self


class CanopyDeleteWidgetConfig(_Input):
    """Delete widget. See https://docs.usecanopy.com/reference/delete-widgetId."""
    operation: Literal["delete_widget"] = Field("delete_widget", json_schema_extra={"ui:hidden": True})
    widgetId: UUID = Field(..., description='widgetId')


class CanopyGetMonitoringReconnectTokenConfig(_Input):
    """Get monitoring reconnect token. See https://docs.usecanopy.com/reference/get-monitoring-reconnect-token."""
    operation: Literal["get_monitoring_reconnect_token"] = Field("get_monitoring_reconnect_token", json_schema_extra={"ui:hidden": True})
    monitoringId: UUID = Field(..., description='ID of Monitoring')


class CanopyRefreshMonitoringConfig(_Input):
    """Refresh monitoring. See https://docs.usecanopy.com/reference/post-monitoring-refresh."""
    operation: Literal["refresh_monitoring"] = Field("refresh_monitoring", json_schema_extra={"ui:hidden": True})
    monitoringId: UUID = Field(..., description='ID of Monitoring')


class CanopyGetMonitoringEventsConfig(_Input):
    """Get monitoring events. See https://docs.usecanopy.com/reference/get-monitoring-events."""
    operation: Literal["get_monitoring_events"] = Field("get_monitoring_events", json_schema_extra={"ui:hidden": True})
    monitoringId: UUID = Field(..., description='ID of Monitoring')


CanopyConnectConfig = Annotated[Union[
    CanopyGetTeamConfig,
    CanopyListPullsConfig,
    CanopyGetPullConfig,
    CanopyUpdatePullConfig,
    CanopyCheckPullPolicyConfig,
    CanopyListWebhooksConfig,
    CanopyCreateWebhookConfig,
    CanopyUpdateWebhookConfig,
    CanopyDeleteWebhookConfig,
    CanopyListMonitoringsConfig,
    CanopyCreateMonitoringConfig,
    CanopyGetMonitoringConfig,
    CanopyUpdateMonitoringConfig,
    CanopyDeleteMonitoringConfig,
    CanopyListWidgetsConfig,
    CanopyCreateWidgetConfig,
    CanopyGetWidgetConfig,
    CanopyUpdateWidgetConfig,
    CanopyDeleteWidgetConfig,
    CanopyGetMonitoringReconnectTokenConfig,
    CanopyRefreshMonitoringConfig,
    CanopyGetMonitoringEventsConfig
], Field(discriminator="operation")]


class CanopyConnectNodeConfig(NodeConfig[CanopyConnectConfig, CanopyConnectCredential]):
    pass


ROUTES = {'get_team': ('GET', '/teams/{teamId}', ()), 'list_pulls': ('GET', '/teams/{teamId}/pulls', ('since', 'before', 'limit', 'offset')), 'get_pull': ('GET', '/teams/{teamId}/pulls/{pullId}', ()), 'update_pull': ('PATCH', '/teams/{teamId}/pulls/{pullId}', ()), 'check_pull_policy': ('POST', '/teams/{teamId}/pulls/{pullId}/policyCheck', ()), 'list_webhooks': ('GET', '/teams/{teamId}/webhooks', ()), 'create_webhook': ('POST', '/teams/{teamId}/webhooks', ()), 'update_webhook': ('PATCH', '/teams/{teamId}/webhooks/{webhookId}', ()), 'delete_webhook': ('DELETE', '/teams/{teamId}/webhooks/{webhookId}', ()), 'list_monitorings': ('GET', '/teams/{teamId}/monitorings', ('limit', 'before', 'pull_id', 'account_identifier', 'status')), 'create_monitoring': ('POST', '/teams/{teamId}/monitorings', ()), 'get_monitoring': ('GET', '/teams/{teamId}/monitorings/{monitoringId}', ('with_pulls', 'limit', 'before')), 'update_monitoring': ('PATCH', '/teams/{teamId}/monitorings/{monitoringId}', ()), 'delete_monitoring': ('DELETE', '/teams/{teamId}/monitorings/{monitoringId}', ()), 'list_widgets': ('GET', '/teams/{teamId}/widgets', ('limit', 'before')), 'create_widget': ('POST', '/teams/{teamId}/widgets', ()), 'get_widget': ('GET', '/teams/{teamId}/widgets/{widgetId}', ()), 'update_widget': ('PATCH', '/teams/{teamId}/widgets/{widgetId}', ()), 'delete_widget': ('DELETE', '/teams/{teamId}/widgets/{widgetId}', ()), 'get_monitoring_reconnect_token': ('GET', '/teams/{teamId}/monitorings/{monitoringId}/reconnectToken', ()), 'refresh_monitoring': ('POST', '/teams/{teamId}/monitorings/{monitoringId}/refresh', ()), 'get_monitoring_events': ('GET', '/teams/{teamId}/monitorings/{monitoringId}/events', ())}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    return value


class CanopyConnectNode(WorkflowNode):
    integration_type = "automation-canopy-connect"
    connection_evidence = ConnectionEvidence(noun="Canopy Connect team", identity_operation="get_team",
        identity_keys=("company_name", "team_id"))

    @classmethod
    def get_config_model(cls):
        return CanopyConnectNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Canopy Connect API key")
        config, credential = self.config.config, self.config.credentials
        method, route, query_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        if "on_success_redirect_url" in config.model_fields_set and config.on_success_redirect_url is None:
            values["on_success_redirect_url"] = None
        route = route.replace("{teamId}", str(credential.canopy_team_id))
        for key in tuple(values):
            if "{" + key + "}" in route:
                route = route.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {key: values.pop(key) for key in query_fields if key in values}
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        auth = httpx.BasicAuth(credential.client_id, credential.client_secret)
        secrets = (credential.client_secret, credential.client_id, auth._auth_header)
        kwargs = {"params": params}
        if method in {"POST", "PATCH"} and config.operation != "refresh_monitoring":
            kwargs["json"] = values
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, auth=auth,
                    headers={"Accept": "application/json"}, **kwargs)
        except httpx.TransportError:
            raise ValueError("Canopy Connect request did not complete" +
                ("; the write outcome is unknown, inspect before retrying" if method != "GET" else "")) from None
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Canopy Connect HTTP {response.status_code}: " + _redact(response.text, secrets)[:1000])
        if len(response.content) > 20000000:
            raise ValueError("Canopy Connect response exceeds the supported JSON size")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Canopy Connect returned invalid JSON; inspect writes before retrying") from None
        if not isinstance(body, dict):
            raise ValueError("Canopy Connect returned an unexpected JSON shape")
        if body.get("error") or body.get("success") is False:
            raise ValueError("Canopy Connect: " + str(_redact(body, secrets))[:1000])
        if config.operation == "get_team" and not all(isinstance(body.get(key), str) and body[key] for key in ("team_id", "company_name")):
            raise ValueError("Canopy Connect team identity is missing")
        output = _redact({"status": "success", "data": body, "http_status": response.status_code}, secrets)
        if config.operation.startswith("list_"):
            output["pagination"] = {"single_page": True, "request": params}
        await self.emit(output)
        return output

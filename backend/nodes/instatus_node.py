"""Automate Instatus status-page communication with a personal API token.

Each operation uses one published Instatus API endpoint. Typed request fields
follow the provider's API 2.0.0 contract, with explicit pagination controls.
Contract: https://raw.githubusercontent.com/instatushq/openapi/main/instatus.json
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class InstatusCredential(BaseModel):
    model_config = ConfigDict(title="Instatus API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.instatus.com/developer",
            "x-credential-instructions": "Copy your API key from Instatus User settings → Developer settings. Paste the key without the Bearer prefix. The connection check reads your user profile; write access depends on your account permissions.",
        })
    credential_type: Literal["instatus_api_token"] = Field("instatus_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Instatus API key without a Bearer prefix")
        return value


class InstatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def resource_id(cls, value, info):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Use an ISO-8601 timestamp with a timezone")
            return value.astimezone(timezone.utc)
        if info.field_name.endswith("_id") and value is not None:
            if value in {".", ".."} or any(c in value for c in "/?#%\\"):
                raise ValueError("Use a single Instatus resource ID")
        return value

class ComponentStatusEntry(InstatusInput):
    id: str | None = None
    status: Literal['OPERATIONAL', 'UNDERMAINTENANCE', 'DEGRADEDPERFORMANCE', 'PARTIALOUTAGE', 'MAJOROUTAGE'] | None = None


class GetProfileConfig(InstatusInput):
    """Get your user profile."""
    operation: Literal['get_profile'] = Field('get_profile', json_schema_extra={"ui:hidden": True})


class ListPagesConfig(InstatusInput):
    """Get your status pages."""
    operation: Literal['list_pages'] = Field('list_pages', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1)
    per_page: int | None = Field(50, le=100, ge=1)


class ListComponentsConfig(InstatusInput):
    """Get all your status page components."""
    operation: Literal['list_components'] = Field('list_components', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    page: int | None = Field(1, ge=1)
    per_page: int | None = Field(50, le=100, ge=1)


class GetComponentConfig(InstatusInput):
    """Get a component."""
    operation: Literal['get_component'] = Field('get_component', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    component_id: str = Field(..., min_length=1, max_length=256)


class CreateComponentConfig(InstatusInput):
    """Create a component."""
    operation: Literal['create_component'] = Field('create_component', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(...)
    description: str | None = Field(None)
    status: Literal['OPERATIONAL', 'UNDERMAINTENANCE', 'DEGRADEDPERFORMANCE', 'PARTIALOUTAGE', 'MAJOROUTAGE'] | None = Field(None)
    order: int | None = Field(None, description='The order of the component on the status page.')
    showUptime: bool | None = Field(None, description='Whether to show the percentage and uptime bar for the component.')
    grouped: bool | None = Field(None, description='Whether the component is a parent component or not, If set to true, make sure to set the group parent id in the `group` field.')
    group: str | None = Field(None, description='The id of the component to group under.')
    archived: bool | None = Field(None)
    translations: dict[str, dict[str, str]] | None = Field(None)


class UpdateComponentConfig(InstatusInput):
    """Update a component."""
    operation: Literal['update_component'] = Field('update_component', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    component_id: str = Field(..., min_length=1, max_length=256)
    name: str | None = Field(None)
    description: str | None = Field(None)
    status: Literal['OPERATIONAL', 'UNDERMAINTENANCE', 'DEGRADEDPERFORMANCE', 'PARTIALOUTAGE', 'MAJOROUTAGE'] | None = Field(None)
    order: int | None = Field(None, description='The order of the component on the status page.')
    showUptime: bool | None = Field(None, description='Whether to show the percentage and uptime bar for the component.')
    grouped: bool | None = Field(None)
    archived: bool | None = Field(None)
    translations: dict[str, dict[str, str]] | None = Field(None)


class DeleteComponentConfig(InstatusInput):
    """Delete a component."""
    operation: Literal['delete_component'] = Field('delete_component', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    component_id: str = Field(..., min_length=1, max_length=256)


class ListIncidentsConfig(InstatusInput):
    """Get all page incidents."""
    operation: Literal['list_incidents'] = Field('list_incidents', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    page: int | None = Field(1, ge=1)
    per_page: int | None = Field(50, le=100, ge=1)
    status: str | None = Field(None)


class GetIncidentConfig(InstatusInput):
    """Get an incident."""
    operation: Literal['get_incident'] = Field('get_incident', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    incident_id: str = Field(..., min_length=1, max_length=256)


class CreateIncidentConfig(InstatusInput):
    """Add an incident."""
    operation: Literal['create_incident'] = Field('create_incident', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(...)
    message: str | None = Field(None)
    components: list[str] | None = Field(None, description='The ids of the components that are affected by the incident.')
    started: datetime | None = Field(None, description='The date and time the incident started, If left empty the time will be set to the current time.')
    status: Literal['INVESTIGATING', 'IDENTIFIED', 'MONITORING', 'RESOLVED'] = Field(...)
    notify: bool | None = Field(None, description='Whether to notify the subscribers of the page and the affected components.')
    shouldPublish: bool | None = Field(True, description='Whether to publish the incident to the page.')
    statuses: list[ComponentStatusEntry] | None = Field(None)
    translations: dict[str, dict[str, str]] | None = Field(None)


class UpdateIncidentConfig(InstatusInput):
    """Update incident."""
    operation: Literal['update_incident'] = Field('update_incident', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    incident_id: str = Field(..., min_length=1, max_length=256)
    name: str | None = Field(None)
    components: list[str] | None = Field(None, description='The ids of the components that are affected by the incident.')
    started: datetime | None = Field(None, description='The date and time the incident started.')
    status: Literal['INVESTIGATING', 'IDENTIFIED', 'MONITORING', 'RESOLVED'] | None = Field(None)
    notify: bool | None = Field(None, description='Whether to notify the subscribers of the page and the affected components.')
    statuses: list[ComponentStatusEntry] | None = Field(None)
    translations: dict[str, dict[str, str]] | None = Field(None)


class DeleteIncidentConfig(InstatusInput):
    """Delete incident."""
    operation: Literal['delete_incident'] = Field('delete_incident', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    incident_id: str = Field(..., min_length=1, max_length=256)


class ListMaintenancesConfig(InstatusInput):
    """Get all page maintenances."""
    operation: Literal['list_maintenances'] = Field('list_maintenances', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    page: int | None = Field(1, ge=1)
    per_page: int | None = Field(50, le=100, ge=1)


class GetMaintenanceConfig(InstatusInput):
    """Get a maintenance."""
    operation: Literal['get_maintenance'] = Field('get_maintenance', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    maintenance_id: str = Field(..., min_length=1, max_length=256)


class CreateMaintenanceConfig(InstatusInput):
    """Add a maintenance."""
    operation: Literal['create_maintenance'] = Field('create_maintenance', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(...)
    message: str | None = Field(None)
    components: list[str] = Field(..., description='The ids of the components that are affected by the maintenance.')
    start: datetime = Field(..., description='The date and time the maintenance will start in ISO-8601 format (UTC Timezone).')
    end: datetime = Field(..., description='The date and time the maintenance will end in ISO-8601 format (UTC Timezone).')
    status: Literal['NOTSTARTEDYET', 'INPROGRESS', 'COMPLETED'] = Field(..., description='The status of the maintenance.')
    notify: bool = Field(..., description='Whether to notify the subscribers of the page and the affected components.')
    duration: int | None = Field(None, description='How many minutes the maintenance will last since the `start` date and time if `autoEnd` is set to `true`.')
    notifyStart: bool = Field(..., description='Whether to notify the subscribers of the page and the affected components when the maintenance **starts**.')
    notifyEnd: bool = Field(..., description='Whether to notify the subscribers of the page and the affected components when the maintenance **ends**.')
    notifyEarly: bool = Field(..., description='Whether to notify the subscribers of the page and the affected components before the maintenance starts.')
    notifyMinutes: int | None = Field(None, description='The number of minutes before the maintenance starts that the subscribers will be notified.')
    autoStart: bool = Field(..., description='Whether to automatically start the maintenance automatically when the date and time reaches the `start` date and time.')
    autoEnd: bool = Field(..., description='Whether to automatically end the maintenance automatically when the date and time« reaches the `end` date and time.')
    isCollapsed: bool | None = Field(None, description='Whether the maintenance is collapsed or not on the page.')
    expandAt: datetime | None = Field(None, description='The date and time the maintenance will expand at in ISO-8601 format (UTC Timezone).')
    statuses: list[ComponentStatusEntry] | None = Field(None)
    translations: dict[str, dict[str, str]] | None = Field(None)


class UpdateMaintenanceConfig(InstatusInput):
    """Update maintenance."""
    operation: Literal['update_maintenance'] = Field('update_maintenance', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    maintenance_id: str = Field(..., min_length=1, max_length=256)
    name: str | None = Field(None)
    message: str = Field(..., description='The message of the maintenance.')
    components: list[str] = Field(..., description='The ids of the components that are affected by the maintenance.')
    start: datetime = Field(..., description='The date and time the maintenance will start.')
    end: datetime = Field(..., description='The date and time the maintenance will end.')
    status: Literal['NOTSTARTEDYET', 'INPROGRESS', 'COMPLETED'] = Field(...)
    notify: bool = Field(..., description='Whether to notify the subscribers of the page and the affected components.')
    autoStart: bool = Field(..., description='Whether to automatically start the maintenance automatically when the date and time reaches the `start` date and time.')
    autoEnd: bool = Field(..., description='Whether to automatically end the maintenance automatically when the date and time« reaches the `end` date and time.')
    duration: int = Field(..., description='How many minutes the maintenance will last since the `start` date and time if `autoEnd` is set to `true`.')
    statuses: list[ComponentStatusEntry] = Field(...)
    translations: dict[str, dict[str, str]] | None = Field(None)


class DeleteMaintenanceConfig(InstatusInput):
    """Delete maintenance."""
    operation: Literal['delete_maintenance'] = Field('delete_maintenance', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    maintenance_id: str = Field(..., min_length=1, max_length=256)


class CreateIncidentUpdateConfig(InstatusInput):
    """Add an incident update."""
    operation: Literal['create_incident_update'] = Field('create_incident_update', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    incident_id: str = Field(..., min_length=1, max_length=256)
    message: str | None = Field(None)
    components: list[str] = Field(..., description='The ids of the components that are affected by the incident.')
    started: datetime | None = Field(None, description='The date and time the incident update happened, If left empty the time will be set to the current time.')
    status: Literal['INVESTIGATING', 'IDENTIFIED', 'MONITORING', 'RESOLVED'] = Field(...)
    notify: bool | None = Field(None, description='Whether to notify the subscribers of the page and the affected components.')
    statuses: list[ComponentStatusEntry] = Field(...)
    translations: dict[str, dict[str, str]] | None = Field(None)


class ListSubscribersConfig(InstatusInput):
    """Get subscribers."""
    operation: Literal['list_subscribers'] = Field('list_subscribers', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    page: int | None = Field(1, ge=1)
    per_page: int | None = Field(50, le=100, ge=1)
    search: str | None = Field(None)


class AddSubscriberConfig(InstatusInput):
    """Add a subscriber."""
    operation: Literal['add_subscriber'] = Field('add_subscriber', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    email: str | None = Field(None, description='The email of the subscriber.')
    phone: str | None = Field(None, description='The phone number of the subscriber.')
    webhook: str | None = Field(None, description='The webhook URL of the subscriber.')
    webhookEmail: str | None = Field(None, description='The webhook email of the webhook subscriber. This is used to send email to the subscriber when a webhook request does not receive a positive response.')
    all: bool | None = Field(None, description='Whether the subscriber is subscribed to all components on the page or not.')
    autoConfirm: bool | None = Field(None, description='Whether the subscriber is automatically confirmed or will receive an email to confirm their subscription.')
    components: list[str] | None = Field(None, description='The ids of the components that the subscriber will be subscribed to, Leave as null if `all` is set to true.')
    language: str | None = Field(None, description='The language of the subscriber in language code (e.g. `en` for English, `fr` for French, `de` for German, etc.).')


class RemoveSubscriberConfig(InstatusInput):
    """Remove a subscriber."""
    operation: Literal['remove_subscriber'] = Field('remove_subscriber', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    subscriber_id: str = Field(..., min_length=1, max_length=256)


class ListTemplatesConfig(InstatusInput):
    """Get all page templates."""
    operation: Literal['list_templates'] = Field('list_templates', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    page: int | None = Field(1, ge=1)
    per_page: int | None = Field(50, le=100, ge=1)


class GetTemplateConfig(InstatusInput):
    """Get a template."""
    operation: Literal['get_template'] = Field('get_template', json_schema_extra={"ui:hidden": True})
    page_id: str = Field(..., min_length=1, max_length=256)
    template_id: str = Field(..., min_length=1, max_length=256)

# Instatus's own MCP server: agents get its tools through a person's Instatus sign-in.
InstatusMcpCredential = mcp_credential("instatus", "https://mcp.instatus.com/mcp", app="Instatus")


InstatusOperation = Annotated[Union[
    GetProfileConfig,
    ListPagesConfig,
    ListComponentsConfig,
    GetComponentConfig,
    CreateComponentConfig,
    UpdateComponentConfig,
    DeleteComponentConfig,
    ListIncidentsConfig,
    GetIncidentConfig,
    CreateIncidentConfig,
    UpdateIncidentConfig,
    DeleteIncidentConfig,
    ListMaintenancesConfig,
    GetMaintenanceConfig,
    CreateMaintenanceConfig,
    UpdateMaintenanceConfig,
    DeleteMaintenanceConfig,
    CreateIncidentUpdateConfig,
    ListSubscribersConfig,
    AddSubscriberConfig,
    RemoveSubscriberConfig,
    ListTemplatesConfig,
    GetTemplateConfig
], Field(discriminator="operation")]


class InstatusNodeConfig(NodeConfig[InstatusOperation, Union[InstatusCredential, InstatusMcpCredential]]):
    pass


# Endpoint, query and body allowlists are taken from the provider's pinned contract.
ROUTES = {'get_profile': ('GET', '/v1/user', [], []),
 'list_pages': ('GET', '/v2/pages', ['page', 'per_page'], []),
 'list_components': ('GET', '/v1/{page_id}/components', ['page', 'per_page'], []),
 'get_component': ('GET', '/v1/{page_id}/components/{component_id}', [], []),
 'create_component': ('POST',
                      '/v1/{page_id}/components',
                      [],
                      ['name',
                       'description',
                       'status',
                       'order',
                       'showUptime',
                       'grouped',
                       'group',
                       'archived',
                       'translations']),
 'update_component': ('PUT',
                      '/v1/{page_id}/components/{component_id}',
                      [],
                      ['name',
                       'description',
                       'status',
                       'order',
                       'showUptime',
                       'grouped',
                       'archived',
                       'translations']),
 'delete_component': ('DELETE', '/v1/{page_id}/components/{component_id}', [], []),
 'list_incidents': ('GET', '/v1/{page_id}/incidents', ['page', 'per_page', 'status'], []),
 'get_incident': ('GET', '/v1/{page_id}/incidents/{incident_id}', [], []),
 'create_incident': ('POST',
                     '/v1/{page_id}/incidents',
                     [],
                     ['name',
                      'message',
                      'components',
                      'started',
                      'status',
                      'notify',
                      'shouldPublish',
                      'statuses',
                      'translations']),
 'update_incident': ('PUT',
                     '/v1/{page_id}/incidents/{incident_id}',
                     [],
                     ['name',
                      'components',
                      'started',
                      'status',
                      'notify',
                      'statuses',
                      'translations']),
 'delete_incident': ('DELETE', '/v1/{page_id}/incidents/{incident_id}', [], []),
 'list_maintenances': ('GET', '/v1/{page_id}/maintenances', ['page', 'per_page'], []),
 'get_maintenance': ('GET', '/v1/{page_id}/maintenances/{maintenance_id}', [], []),
 'create_maintenance': ('POST',
                        '/v1/{page_id}/maintenances',
                        [],
                        ['name',
                         'message',
                         'components',
                         'start',
                         'end',
                         'status',
                         'notify',
                         'duration',
                         'notifyStart',
                         'notifyEnd',
                         'notifyEarly',
                         'notifyMinutes',
                         'autoStart',
                         'autoEnd',
                         'isCollapsed',
                         'expandAt',
                         'statuses',
                         'translations']),
 'update_maintenance': ('PUT',
                        '/v1/{page_id}/maintenances/{maintenance_id}',
                        [],
                        ['name',
                         'message',
                         'components',
                         'start',
                         'end',
                         'status',
                         'notify',
                         'autoStart',
                         'autoEnd',
                         'duration',
                         'statuses',
                         'translations']),
 'delete_maintenance': ('DELETE', '/v1/{page_id}/maintenances/{maintenance_id}', [], []),
 'create_incident_update': ('POST',
                            '/v1/{page_id}/incidents/{incident_id}/incident-updates',
                            [],
                            ['message',
                             'components',
                             'started',
                             'status',
                             'notify',
                             'statuses',
                             'translations']),
 'list_subscribers': ('GET', '/v1/{page_id}/subscribers', ['page', 'per_page', 'search'], []),
 'add_subscriber': ('POST',
                    '/v1/{page_id}/subscribers',
                    [],
                    ['email',
                     'phone',
                     'webhook',
                     'webhookEmail',
                     'all',
                     'autoConfirm',
                     'components',
                     'language']),
 'remove_subscriber': ('DELETE', '/v1/{page_id}/subscribers/{subscriber_id}', [], []),
 'list_templates': ('GET', '/v1/{page_id}/templates', ['page', 'per_page'], []),
 'get_template': ('GET', '/v1/{page_id}/templates/{template_id}', [], [])}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class InstatusNode(WorkflowNode):
    integration_type = "automation-instatus"
    credential_provider_labels = {"instatus": "Instatus Account"}
    connection_evidence = ConnectionEvidence(
        noun="Instatus account", identity_operation="get_profile",
        identity_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return InstatusNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Instatus API token")
        op = self.config.config
        method, template, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        path = template
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values} if body_fields else None
        token = self.config.credentials.api_token
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.instatus.com" + path,
                params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                         "Content-Type": "application/json"})
        if not response.is_success:
            # Keep provider rejection text so the shared connect seam can explain it.
            message = _redact(response.text[:2000], token)
            result = {"status": "error", "success": False, "http_status": response.status_code,
                      "message": message}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Instatus response exceeds the JSON size limit")
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Expected an Instatus JSON object or list")
            if isinstance(data, dict) and (data.get("error") or data.get("errors")):
                result = {"status": "error", "success": False, "message": _redact(str(data), token)}
            else:
                result = {"status": "success", "data": _redact(data, token)}
                if op.operation.startswith("list_"):
                    # Return one explicit API page. A full page may have a successor.
                    result["pagination"] = {"page": values.get("page", 1),
                        "per_page": values.get("per_page", 50),
                        "next_page": values.get("page", 1) + 1 if isinstance(data, list) and len(data) == values.get("per_page", 50) else None}
        await self.emit(result)
        return result

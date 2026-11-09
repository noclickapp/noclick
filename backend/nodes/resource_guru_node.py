"""Resource Guru scheduling actions and signed client change deliveries.

Routes, fields and HMAC delivery format follow the pinned public OpenAPI v1.0.0.
Only the client webhook has a provider-authored example, so other events are not subscribed.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.resource_guru import RESOURCE_GURU_SCOPES

BASE = "https://api.resourceguruapp.com"
DOCS = "https://resourceguruapp.com/docs/api"

class ResourceGuruOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Resource Guru Account", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "resource-guru",
        "x-oauth-scopes": RESOURCE_GURU_SCOPES.declared_scopes(),
        "x-credential-url": "https://developers.resourceguruapp.com",
        "x-credential-instructions": "Connect Resource Guru with OAuth. Account owners or administrators can activate client change triggers. An existing access token can also be supplied; add its refresh token and expiry to renew it automatically.",
    })
    credential_type: Literal["resource_guru_oauth"] = Field("resource_guru_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token Expiry")

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

# Every entry is one fixed method and path in the published contract.
OPERATIONS = {
    'get_me': ('GET', '/v1/me', {}, (), ()),
    'list_accounts': ('GET', '/v1/accounts', {}, (), ()),
    'list_bookings': ('GET', '/v1/{account}/bookings', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'limit': (int, Field(50, ge=1, le=500, description="Maximum records in this page.")), 'offset': (int, Field(0, ge=0, description="Records to skip. Increase by the page size to read the next page.")), 'start_date': (date | None, Field(None, title="Start Date")), 'end_date': (date | None, Field(None, title="End Date"))}, ('limit', 'offset', 'start_date', 'end_date'), ()),
    'get_booking': ('GET', '/v1/{account}/bookings/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID"))}, (), ()),
    'create_booking': ('POST', '/v1/{account}/bookings', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'resource_id': (int, Field(..., ge=1, title='Resource ID')), 'start_date': (date, Field(..., title="Start Date")), 'end_date': (date, Field(..., title="End Date")), 'duration': (int, Field(..., ge=1, le=1440, title="Minutes per Day")), 'details': (str | None, Field(None, title='Details', max_length=65535)), 'client_id': (int | None, Field(None, ge=1, title='Client ID')), 'project_id': (int | None, Field(None, ge=1, title='Project ID')), 'billable': (bool | None, Field(None, title='Billable'))}, (), ('resource_id', 'start_date', 'end_date', 'duration', 'details', 'client_id', 'project_id', 'billable')),
    'update_booking': ('PUT', '/v1/{account}/bookings/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID")), 'resource_id': (int | None, Field(None, ge=1, title='Resource ID')), 'start_date': (date | None, Field(None, title="Start Date")), 'end_date': (date | None, Field(None, title="End Date")), 'duration': (int | None, Field(None, ge=1, le=1440, title="Minutes per Day")), 'details': (str | None, Field(None, title='Details', max_length=65535)), 'client_id': (int | None, Field(None, ge=1, title='Client ID')), 'project_id': (int | None, Field(None, ge=1, title='Project ID')), 'billable': (bool | None, Field(None, title='Billable'))}, (), ('resource_id', 'start_date', 'end_date', 'duration', 'details', 'client_id', 'project_id', 'billable')),
    'delete_booking': ('DELETE', '/v1/{account}/bookings/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID"))}, (), ()),
    'list_clients': ('GET', '/v1/{account}/clients', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'limit': (int, Field(50, ge=1, le=500, description="Maximum records in this page.")), 'offset': (int, Field(0, ge=0, description="Records to skip. Increase by the page size to read the next page."))}, ('limit', 'offset'), ()),
    'get_client': ('GET', '/v1/{account}/clients/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID"))}, (), ()),
    'create_client': ('POST', '/v1/{account}/clients', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'name': (str, Field(..., title='Name', max_length=255, min_length=1)), 'notes': (str | None, Field(None, title='Notes', max_length=65535)), 'archived': (bool | None, Field(None, title='Archived'))}, (), ('name', 'notes', 'archived')),
    'update_client': ('PUT', '/v1/{account}/clients/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID")), 'name': (str | None, Field(None, title='Name', max_length=255)), 'notes': (str | None, Field(None, title='Notes', max_length=65535)), 'archived': (bool | None, Field(None, title='Archived'))}, (), ('name', 'notes', 'archived')),
    'delete_client': ('DELETE', '/v1/{account}/clients/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID"))}, (), ()),
    'list_projects': ('GET', '/v1/{account}/projects', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'limit': (int, Field(50, ge=1, le=500, description="Maximum records in this page.")), 'offset': (int, Field(0, ge=0, description="Records to skip. Increase by the page size to read the next page."))}, ('limit', 'offset'), ()),
    'get_project': ('GET', '/v1/{account}/projects/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID"))}, (), ()),
    'create_project': ('POST', '/v1/{account}/projects', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'name': (str, Field(..., title='Name', max_length=255, min_length=1)), 'notes': (str | None, Field(None, title='Notes', max_length=65535)), 'archived': (bool | None, Field(None, title='Archived')), 'client_id': (int | None, Field(None, ge=1, title='Client ID')), 'project_code': (str | None, Field(None, title='Project Code', max_length=255)), 'default_billable': (bool | None, Field(None, title='Default Billable'))}, (), ('name', 'notes', 'archived', 'client_id', 'project_code', 'default_billable')),
    'update_project': ('PUT', '/v1/{account}/projects/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID")), 'name': (str | None, Field(None, title='Name', max_length=255)), 'notes': (str | None, Field(None, title='Notes', max_length=65535)), 'archived': (bool | None, Field(None, title='Archived')), 'client_id': (int | None, Field(None, ge=1, title='Client ID')), 'project_code': (str | None, Field(None, title='Project Code', max_length=255)), 'default_billable': (bool | None, Field(None, title='Default Billable'))}, (), ('name', 'notes', 'archived', 'client_id', 'project_code', 'default_billable')),
    'delete_project': ('DELETE', '/v1/{account}/projects/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID"))}, (), ()),
    'list_resources': ('GET', '/v1/{account}/resources', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'limit': (int, Field(50, ge=1, le=500, description="Maximum records in this page.")), 'offset': (int, Field(0, ge=0, description="Records to skip. Increase by the page size to read the next page."))}, ('limit', 'offset'), ()),
    'get_resource': ('GET', '/v1/{account}/resources/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID"))}, (), ()),
    'create_resource': ('POST', '/v1/{account}/resources', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'resource_type_id': (int, Field(..., ge=1, title='Resource Type ID')), 'name': (str | None, Field(None, title='Resource Name', max_length=255)), 'first_name': (str | None, Field(None, title='First Name', max_length=255)), 'last_name': (str | None, Field(None, title='Last Name', max_length=255)), 'email': (str | None, Field(None, title='Email', max_length=255)), 'notes': (str | None, Field(None, title='Notes', max_length=65535))}, (), ('resource_type_id', 'name', 'first_name', 'last_name', 'email', 'notes')),
    'update_resource': ('PUT', '/v1/{account}/resources/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID")), 'name': (str | None, Field(None, title='Resource Name', max_length=255)), 'first_name': (str | None, Field(None, title='First Name', max_length=255)), 'last_name': (str | None, Field(None, title='Last Name', max_length=255)), 'notes': (str | None, Field(None, title='Notes', max_length=65535)), 'archived': (bool | None, Field(None, title='Archived'))}, (), ('name', 'first_name', 'last_name', 'notes', 'archived')),
    'list_downtimes': ('GET', '/v1/{account}/downtimes', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'limit': (int, Field(50, ge=1, le=500, description="Maximum records in this page.")), 'offset': (int, Field(0, ge=0, description="Records to skip. Increase by the page size to read the next page.")), 'from_date': (date | None, Field(None, title="From Date")), 'to_date': (date | None, Field(None, title="To Date"))}, ('limit', 'offset', 'from_date', 'to_date'), ()),
    'create_downtime': ('POST', '/v1/{account}/downtimes', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'resource_id': (int, Field(..., ge=1, title='Resource ID')), 'from_date': (date, Field(..., title="From Date")), 'to_date': (date, Field(..., title="To Date")), 'start_time': (int, Field(..., ge=0, le=1440, title="Start Time", description="Minutes after midnight.")), 'end_time': (int, Field(..., ge=0, le=1440, title="End Time", description="Minutes after midnight.")), 'downtime_type_id': (int | None, Field(None, ge=1, title='Time Off Type ID')), 'details': (str | None, Field(None, title='Details', max_length=65535))}, (), ('resource_id', 'from_date', 'to_date', 'start_time', 'end_time', 'downtime_type_id', 'details')),
    'delete_downtime': ('DELETE', '/v1/{account}/downtimes/{id}', {'account': (str, Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID", description="Account slug in the Resource Guru URL, for example example-corp.")), 'id': (int, Field(..., ge=1, title="Record ID"))}, (), ()),
}


def _config(name, spec):
    method, path, fields, query, body = spec
    label = name.replace("_", " ").title()
    return create_model("ResourceGuru" + label.replace(" ", "") + "Config", __base__=_Input, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "ui:hidden": True, "x-display-name": label, "x-category": "Actions", "x-is-trigger": False})), **fields)

CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})

class ResourceGuruOnClientChangedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_client_changed"] = Field("on_client_changed", title="On Client Changed", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On Client Changed", "x-category": "Triggers", "x-is-trigger": True})
    account: str = Field(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$", title="Account URL ID")
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

ResourceGuruConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ResourceGuruOnClientChangedConfig,)], Field(discriminator="operation")]

class ResourceGuruNodeConfig(NodeConfig[ResourceGuruConfig, ResourceGuruOAuthCredential]):
    pass

class ResourceGuruNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-resource-guru"
    scope_registry = RESOURCE_GURU_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="accounts", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return ResourceGuruNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data or not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.resource_guru_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="resource-guru")

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = "Request failed"
            raise ValueError(f"Resource Guru API error {response.status_code}: {detail}")
        return response.json() if response.content else {"ok": True}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"account": config.get("account")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        parsed = ResourceGuruOnClientChangedConfig.model_validate(config)
        secret = secrets.token_hex(32)
        result = await cls._request(credential["access_token"], "POST",
            "/v1/" + quote(parsed.account, safe="") + "/webhooks", body={
                "name": f"NoClick {node_id}"[:255], "payload_url": webhook_url,
                "events": ["clients"], "secret": secret, "send_secret_header": False, "paused": False})
        if not isinstance(result, dict) or not result.get("id"):
            raise ValueError("Resource Guru did not return a webhook ID")
        return {"external_webhook_id": str(result["id"]), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = config.get("external_webhook_id")
        if not webhook_id or not credential:
            return
        parsed = ResourceGuruOnClientChangedConfig.model_validate(config)
        await cls._request(credential["access_token"], "DELETE",
            "/v1/" + quote(parsed.account, safe="") + "/webhooks/" + quote(str(webhook_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = config.get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-resourceguru-signature"), "")
        if (not secret or not isinstance(signature, str) or len(signature) != 64
                or any(char not in "0123456789abcdef" for char in signature)):
            return False
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        record = payload.get("payload")
        return (isinstance(record, dict) and record.get("type") == "client"
            and record.get("action") in ("create", "update", "delete") and bool(record.get("id")))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": "on_client_changed", "data": payload, "account": config["account"]}

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get("data", output)
        record = event.get("payload", {})
        if record.get("type") != "client" or not record.get("id"):
            return None
        record_id = record["id"]
        name = record.get("name") or str(record_id)
        account = output.get("account", "")
        # The published delivery identifies the changed client but names no actor.
        text = (f"Resource Guru client {record.get('action')}: {name}\n"
            f"Account: {account}; client ID: {record_id}; delivery ID: {event.get('id')}; timestamp: {event.get('timestamp')}\n"
            f"Notes: {record.get('notes') or ''}\n"
            f"To act: get_client, update_client or delete_client with account={account} and id={record_id}.")
        return {"text": text, "conversation_key": f"{account}:client:{record_id}", "title": f"Resource Guru: {name}"}

    async def execute(self, inputs):
        if not isinstance(self.config, ResourceGuruNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Resource Guru account")
        op = self.config.config
        if isinstance(op, ResourceGuruOnClientChangedConfig):
            return {"status": "success", "operation": op.operation, "data": inputs}
        credential = self.config.credentials
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.resource_guru_oauth import refresh_access_token
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data, refresh=refresh_access_token,
            provider="resource-guru", caller_path="execute")
        credential.access_token = data["access_token"]
        credential.refresh_token = data.get("refresh_token")
        credential.expires_at = data.get("expires_at")
        self.scope_registry.require(op.operation)
        method, path, fields, query_fields, body_fields = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("account", "id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        rename = {"from_date": "from", "to_date": "to"}
        params = {rename.get(k,k): str(values[k]) for k in query_fields if k in values}
        body = {rename.get(k,k): values[k] for k in body_fields if k in values}
        if op.operation == "create_downtime":
            body["resource_ids"] = [body.pop("resource_id")]
        result = await self._request(token, method, path, params=params or None,
            body=body if body_fields else None)
        return {"status": "success", "operation": op.operation, "data": result}

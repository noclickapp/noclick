"""Dynatrace Account Management API actions and account audit polling.

Routes and bodies follow the published Account Management OpenAPI 1.0 contract.
OAuth uses the declared Dynatrace SSO provider; API tokens stay on api.dynatrace.com.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.dynatrace import DYNATRACE_SCOPES

BASE_URL = "https://api.dynatrace.com"
AUTH_DOCS = "https://docs.dynatrace.com/docs/manage/identity-access-management/access-tokens-and-oauth-clients/oauth-clients"
AUDIT_DOCS = "https://docs.dynatrace.com/docs/dynatrace-api/account-management-api/account-audits-api/get-account-audits"


def _segment(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Paste a single Dynatrace account or resource ID")
    return value


class DynatraceOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Dynatrace OAuth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "dynatrace",
            "x-oauth-scopes": sorted(DYNATRACE_SCOPES.declared_scopes()),
            "x-credential-url": AUTH_DOCS,
            "x-credential-instructions": (
                "Connect your Dynatrace account using OAuth. Enter the account UUID from Account Management. "
                "The OAuth client must allow the account-management permissions needed by these operations "
                "and openid, profile and offline_access for identity and refresh. The user must also have "
                "the corresponding account permissions. Register the NoClick callback URL with the client. "
                "Classic environment API tokens do not grant Account Management access."
            ),
        })
    credential_type: Literal["dynatrace_oauth"] = Field("dynatrace_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Bearer access token", min_length=1, max_length=8192,
                            json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token expiry")
    account_uuid: str = Field(..., title="Account UUID", description="Account Management > Identity & access management > OAuth clients.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Bearer access token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste only the bearer token, without the Authorization header")
        return value

    @field_validator("account_uuid")
    @classmethod
    def account(cls, value):
        return _segment(value.strip())


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: tuple[str, ...] = ()
    query: tuple[tuple[str, str], ...] = ()
    body: tuple[tuple[str, str], ...] = ()
    root: Optional[str] = None
    category: str = "Account"


IAM = "/iam/v1/accounts/{account_uuid}"
POLICIES = "/iam/v1/repo/account/{account_uuid}/policies"
OPERATIONS = {
    "list_users": Operation("GET", IAM + "/users", ("include_service_users",), (("include_service_users", "service-users"),), category="Users"),
    "create_user": Operation("POST", IAM + "/users", ("email",), body=(("email", "email"),), category="Users"),
    "get_user_groups": Operation("GET", IAM + "/users/{email}", ("email",), category="Users"),
    "add_user_to_groups": Operation("POST", IAM + "/users/{email}", ("email", "group_ids_json"), root="group_ids_json", category="Users"),
    "remove_user": Operation("DELETE", IAM + "/users/{email}", ("email",), category="Users"),
    "replace_user_groups": Operation("PUT", IAM + "/users/{email}/groups", ("email", "group_ids_json"), root="group_ids_json", category="Users"),
    "remove_user_from_groups": Operation("DELETE", IAM + "/users/{email}/groups", ("email", "group_ids_json"), (("group_ids_json", "group-uuid"),), category="Users"),
    "list_groups": Operation("GET", IAM + "/groups", category="Groups"),
    "create_group": Operation("POST", IAM + "/groups", ("name", "group_description", "federated_values_json"), body=(("name", "name"), ("group_description", "description"), ("federated_values_json", "federatedAttributeValues")), root="single_group", category="Groups"),
    "update_group": Operation("PUT", IAM + "/groups/{group_uuid}", ("group_uuid", "name", "group_description", "federated_values_json"), body=(("name", "name"), ("group_description", "description"), ("federated_values_json", "federatedAttributeValues")), category="Groups"),
    "delete_group": Operation("DELETE", IAM + "/groups/{group_uuid}", ("group_uuid",), category="Groups"),
    "list_group_members": Operation("GET", IAM + "/groups/{group_uuid}/users", ("group_uuid",), category="Groups"),
    "list_policies": Operation("GET", POLICIES, ("policy_name",), (("policy_name", "name"),), category="Policies"),
    "get_policy": Operation("GET", POLICIES + "/{policy_uuid}", ("policy_uuid",), category="Policies"),
    "create_policy": Operation("POST", POLICIES, ("name", "policy_description", "statement_query", "tags_json"), body=(("name", "name"), ("policy_description", "description"), ("statement_query", "statementQuery"), ("tags_json", "tags")), category="Policies"),
    "update_policy": Operation("PUT", POLICIES + "/{policy_uuid}", ("policy_uuid", "name", "policy_description", "statement_query", "tags_json"), body=(("name", "name"), ("policy_description", "description"), ("statement_query", "statementQuery"), ("tags_json", "tags")), category="Policies"),
    "delete_policy": Operation("DELETE", POLICIES + "/{policy_uuid}", ("policy_uuid", "force"), (("force", "force"),), category="Policies"),
    "list_environments": Operation("GET", "/env/v2/accounts/{account_uuid}/environments", category="Environments"),
    "list_subscriptions": Operation("GET", "/sub/v2/accounts/{account_uuid}/subscriptions", category="Subscriptions"),
    "get_subscription": Operation("GET", "/sub/v2/accounts/{account_uuid}/subscriptions/{subscription_uuid}", ("subscription_uuid",), category="Subscriptions"),
    "list_audit_logs": Operation("GET", "/audit/v1/accounts/{account_uuid}", ("start_time", "end_time", "audit_filter", "limit"), (("start_time", "startTime"), ("end_time", "endTime"), ("audit_filter", "filter"), ("limit", "limit")), category="Audit logs"),
}


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("group_uuid", "policy_uuid", "subscription_uuid", check_fields=False)
    @classmethod
    def identifier(cls, value):
        return _segment(value)

    @field_validator("email", check_fields=False)
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s/@]+@[^\s/]+", value) or len(value) > 320:
            raise ValueError("Enter the user's email address")
        return value

    @field_validator("group_ids_json", "federated_values_json", "tags_json", check_fields=False)
    @classmethod
    def string_array(cls, value, info):
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("Enter a JSON array of strings") from None
        if not isinstance(parsed, list) or any(not isinstance(x, str) for x in parsed):
            raise ValueError("Enter a JSON array of strings")
        if info.field_name == "group_ids_json":
            if len(parsed) > (20 if info.data.get("operation") == "remove_user_from_groups" else 200):
                raise ValueError("Too many groups (remove: 20; add/replace: 200)")
            if info.data.get("operation") != "replace_user_groups" and not parsed:
                raise ValueError("Choose at least one group")
            for item in parsed:
                _segment(item)
        return value


JSON_UI = {"ui:widget": "code_editor", "x-code-language": "json"}
FIELDS = {
    "include_service_users": (Optional[bool], Field(None, title="Include service users")),
    "email": (str, Field(..., title="User email")),
    "group_uuid": (str, Field(..., title="Group UUID")),
    "group_ids_json": (str, Field(..., title="Group UUIDs (JSON)", max_length=40000, description='Array of group UUID strings. Replace overwrites membership; [] removes all memberships.', json_schema_extra=JSON_UI)),
    "name": (str, Field(..., title="Name", min_length=1, max_length=1000)),
    "group_description": (Optional[str], Field(None, title="Description", max_length=255)),
    "federated_values_json": (Optional[str], Field(None, title="Federated attribute values (JSON)", max_length=40000, description="On update, omitting this field can change a SAML group to LOCAL. Supply all values you want to retain.", json_schema_extra=JSON_UI)),
    "policy_uuid": (str, Field(..., title="Policy UUID")),
    "policy_name": (Optional[str], Field(None, title="Exact policy name")),
    "policy_description": (str, Field(..., title="Policy description", max_length=10000)),
    "statement_query": (str, Field(..., title="Policy statement", min_length=1, max_length=100000, description="Dynatrace IAM statement, for example ALLOW storage:logs:read;")),
    "tags_json": (Optional[str], Field(None, title="Tags (JSON)", max_length=40000, json_schema_extra=JSON_UI)),
    "force": (bool, Field(False, title="Delete even if policy is in use")),
    "subscription_uuid": (str, Field(..., title="Subscription UUID")),
    "start_time": (Optional[str], Field(None, title="Start time", description="ISO-8601, Unix epoch milliseconds, or now()-2d.")),
    "end_time": (Optional[str], Field(None, title="End time", description="ISO-8601, Unix epoch milliseconds, or now().")),
    "audit_filter": (Optional[str], Field(None, title="Audit filter", max_length=256, description="Dynatrace audit filter expression.")),
    "limit": (int, Field(50, title="Maximum audit events", ge=1, le=10000)),
}


def _model(name, spec):
    label = name.replace("_", " ").title()
    return create_model("Dynatrace" + name.title().replace("_", "") + "Config", __base__=_Input,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-display-name": label, "x-category": spec.category})),
        **{field: FIELDS[field] for field in spec.fields})


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class DynatraceOnNewAuditEventConfig(PollTriggerConfigBase):
    operation: Literal["on_new_audit_event"] = Field("on_new_audit_event", json_schema_extra={
        "const": "on_new_audit_event", "ui:hidden": True, "x-is-trigger": True,
        "x-display-name": "On New Account Audit Event", "x-category": "Triggers"})
    lookback_hours: int = Field(24, ge=1, le=168, title="Lookback hours", description="Poll this rolling time window. Existing events are baselined when armed. Use a schedule shorter than the window; outages beyond it can miss events.")
    audit_filter: Optional[str] = Field(None, title="Audit filter", max_length=256)
    limit: int = Field(1000, ge=1, le=10000, title="Maximum events per window", description="At this limit, results may be incomplete. Narrow the filter/window or increase the limit.")
    allow_partial_results: bool = Field(False, title="Allow incomplete audit windows", description="By default a warning or full page stops polling without consuming seen state. Enable to emit the returned events with an explicit incompleteness warning; events missing from the API response may be missed.")


DynatraceConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (DynatraceOnNewAuditEventConfig,)], Field(discriminator="operation")]


class DynatraceNodeConfig(NodeConfig[DynatraceConfig, DynatraceOAuthCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k != "authenticationToken"}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class DynatraceAPIError(ValueError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(f"Dynatrace API {status}: {detail}")


class DynatraceNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-dynatrace"
    connection_evidence = ConnectionEvidence(noun="groups", operation="list_groups", label_keys=("name", "uuid"))
    scope_registry = DYNATRACE_SCOPES
    edit_examples = ["Add a user to a Dynatrace group", "Create an account IAM policy", "Watch for new account audit events"]

    @classmethod
    def get_config_model(cls):
        return DynatraceNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.dynatrace_oauth import OAUTH_PROVIDER
        if not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data), provider="dynatrace",
            additional_token_fields=OAUTH_PROVIDER.credential_fields)

    async def _freshen(self, credential):
        if not credential.refresh_token:
            return
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.dynatrace_oauth import OAUTH_PROVIDER
        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=OAUTH_PROVIDER.bind_refresh(data), provider="dynatrace",
            caller_path="execute", additional_token_fields=OAUTH_PROVIDER.credential_fields)
        for field in ("access_token", "refresh_token", "expires_at", "account_uuid"):
            setattr(credential, field, data.get(field))

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("Dynatrace request did not complete; inspect writes before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json()
                detail = detail.get("message") or detail.get("error") or detail if isinstance(detail, dict) else detail
                detail = json.dumps(detail) if not isinstance(detail, str) else detail
            except ValueError:
                detail = response.text[:2000] or "request rejected"
            raise DynatraceAPIError(response.status_code, _redact(detail, credential.access_token))
        try:
            data = response.json() if response.content else None
        except ValueError:
            # User creation documents a UUID response without a JSON media type.
            if method != "POST" or not path.endswith("/users"):
                raise ValueError("Dynatrace returned invalid JSON") from None
            data = response.text
        if isinstance(data, dict) and "error" in data and data["error"] is True:
            raise DynatraceAPIError(response.status_code, _redact(str(data.get("message") or "request failed"), credential.access_token))
        return data, response.status_code

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Dynatrace account")
        credential, config = self.config.credentials, self.config.config
        self.scope_registry.require(config.operation)
        await self._freshen(credential)
        if isinstance(config, DynatraceOnNewAuditEventConfig):
            return await self._poll_audits(credential, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec.path.replace("{account_uuid}", quote(credential.account_uuid, safe=""))
        for key, value in values.items():
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(value), safe=""))
        def wire(key):
            return json.loads(values[key]) if key.endswith("_json") else values[key]
        params = {target: wire(source) for source, target in spec.query if source in values}
        body = {target: wire(source) for source, target in spec.body if source in values} if spec.body else None
        if spec.root == "single_group":
            body = [body]
        elif spec.root:
            body = wire(spec.root)
        data, status = await self._request(credential, spec.method, path, params=params, body=body)
        return {"data": _redact(data, credential.access_token), "http_status": status}

    async def _poll_audits(self, credential, config):
        params = {"startTime": f"now()-{config.lookback_hours}h", "endTime": "now()", "limit": config.limit}
        if config.audit_filter is not None:
            params["filter"] = config.audit_filter
        data, _ = await self._request(credential, "GET", "/audit/v1/accounts/" + quote(credential.account_uuid, safe=""), params=params)
        if not isinstance(data, dict) or not isinstance(data.get("audits"), list) or not isinstance(data.get("warnings"), list):
            raise ValueError("Dynatrace audit response must contain audits and warnings arrays")
        audits = data["audits"]
        incomplete = bool(data["warnings"]) or len(audits) >= config.limit
        if incomplete and not config.allow_partial_results:
            raise ValueError("Dynatrace audit window may be truncated; narrow the filter/window or increase the event limit")
        for event in audits:
            if not isinstance(event, dict) or not isinstance(event.get("eventId"), str) or not event["eventId"]:
                raise ValueError("Dynatrace audit event is missing its eventId")
        fresh = await self._filter_unseen(audits, lambda event: event["eventId"])
        return {"audits": _redact(fresh, credential.access_token), "new_event_count": len(fresh), "warnings": _redact(data["warnings"], credential.access_token), "window_may_be_incomplete": incomplete}

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]):
        audits = output.get("audits") if isinstance(output, dict) else None
        if not isinstance(audits, list):
            return super().resolve_agent_event(output)
        if not audits:
            return None
        lines = []
        if output.get("window_may_be_incomplete"):
            lines.append("Warning: this audit window may be incomplete. Events absent from the API response may be missed. Narrow the filter/window or increase the limit.")
        for event in audits[:20]:
            if not isinstance(event, dict):
                continue
            lines.append(
                f"{event.get('user') or 'Unknown actor'}: {event.get('eventType') or 'change'} "
                f"{event.get('resource') or 'resource'} {event.get('resourceName') or ''} "
                f"(resourceId={event.get('resourceId')}, accountUuid={event.get('accountUuid')}, "
                f"eventId={event.get('eventId')}, timestamp={event.get('timestamp')}, "
                f"outcome={event.get('eventOutcome')}). Reason: {str(event.get('eventReason') or '')[:500]}"
            )
        if len(audits) > 20:
            lines.append(f"Plus {len(audits) - 20} more events in the audits output.")
        return {"text": "Dynatrace account audit events:\n" + "\n".join(lines),
                "title": "Dynatrace account audit events", "conversation_key": None}

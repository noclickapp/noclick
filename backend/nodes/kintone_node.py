"""Kintone app records and metadata via app-scoped API tokens.

Contract: kintone/openapi-spec 2026.11.11. API reference:
https://kintone.dev/en/docs/kintone/rest-api/
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Union
import re
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client, normalize_provider_https_origin


class KintoneAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Kintone API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://kintone.dev/en/docs/common/authentication/",
            "x-credential-instructions": "In your app settings, open API Token, generate a token with the permissions your workflow needs, and update the app. Paste the token, your tenant URL, and that app's ID. Enable View records for reads; enable Add, Edit, or Delete records for writes. The app-name connection check requires View or Add records permission. App settings reads may require App management permission. Multiple app tokens for lookup fields can be separated by commas. NoClick checks the app name to verify access.",
        })
    credential_type: Literal["kintone_api_token"] = Field("kintone_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    tenant_url: str = Field(..., title="Tenant URL", description="Your HTTPS tenant origin, such as https://example.kintone.com or https://example.cybozu.com.")
    app_id: int = Field(..., title="App ID", ge=1, description="The numeric ID in your app URL. Used as the default app and for the connection check.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*", value):
            raise ValueError("Paste API tokens only, separated by commas if needed")
        return value

    @field_validator("tenant_url", mode="before")
    @classmethod
    def tenant(cls, value):
        for domain in ("kintone.com", "cybozu.com"):
            try:
                return normalize_provider_https_origin(value, domain, field_name="Tenant URL")
            except SSRFError:
                pass
        raise ValueError("Use your HTTPS Kintone tenant origin on kintone.com or cybozu.com")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _App(_Input):
    app_id: int | None = Field(None, ge=1, description="Leave blank to use the credential's app ID.")


class _Record(_App):
    record_id: int = Field(..., ge=1)


class WritableField(_Input):
    value: Any = Field(..., description="Kintone field value, matching the app's field type. For attachments, use existing fileKey objects.")


class KintoneGetApp(_App):
    """Get general app information, including its name."""
    operation: Literal["get_app"] = "get_app"


class KintoneGetFields(_App):
    """Get field codes, types and settings."""
    operation: Literal["get_fields"] = "get_fields"
    lang: Literal["default", "user", "en", "ja", "zh"] = "default"


class KintoneGetViews(KintoneGetFields):
    """Get the app's configured views."""
    operation: Literal["get_views"] = "get_views"


class KintoneGetProcess(KintoneGetFields):
    """Get process management states and actions."""
    operation: Literal["get_process"] = "get_process"


class KintoneGetRecord(_Record):
    """Read a record by its numeric ID."""
    operation: Literal["get_record"] = "get_record"


class KintoneListRecords(_App):
    """Read one page. Use Kintone query syntax with limit (max 500) and offset (max 10000), or use cursors for larger exports."""
    operation: Literal["list_records"] = "list_records"
    query: str | None = Field(None, max_length=16384, description="Kintone query, not SQL. Get field codes with Get fields first.")
    total_count: bool = False


class KintoneCreateRecord(_App):
    """Add one record with field codes mapped to value objects."""
    operation: Literal["create_record"] = "create_record"
    record: dict[str, WritableField]


class KintoneUpdateRecord(_Record):
    """Update specified fields of one record, optionally checking its revision."""
    operation: Literal["update_record"] = "update_record"
    record: dict[str, WritableField]
    revision: int | None = Field(None, ge=-1)


class RecordUpdate(_Input):
    id: int = Field(..., ge=1)
    record: dict[str, WritableField]
    revision: int | None = Field(None, ge=-1)


class KintoneCreateRecords(_App):
    """Add up to 100 records in one request."""
    operation: Literal["create_records"] = "create_records"
    records: list[dict[str, WritableField]] = Field(..., min_length=1, max_length=100)


class KintoneUpdateRecords(_App):
    """Update up to 100 records by ID in one request."""
    operation: Literal["update_records"] = "update_records"
    records: list[RecordUpdate] = Field(..., min_length=1, max_length=100)


class KintoneDeleteRecords(_App):
    """Delete up to 100 records. Revisions, when supplied, correspond to IDs in order."""
    operation: Literal["delete_records"] = "delete_records"
    ids: list[Annotated[int, Field(ge=1)]] = Field(..., min_length=1, max_length=100)
    revisions: list[Annotated[int, Field(ge=-1)]] | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def matching_revisions(self):
        if self.revisions is not None and len(self.revisions) != len(self.ids):
            raise ValueError("Supply one revision per record ID")
        return self


class KintoneGetComments(_Record):
    """Read one page of comments; newer and older indicate remaining pages."""
    operation: Literal["get_comments"] = "get_comments"
    offset: int = Field(0, ge=0)
    limit: int = Field(10, ge=1, le=10)
    order: Literal["ASC", "DESC"] = "DESC"


class Mention(_Input):
    code: str = Field(..., min_length=1)
    type: Literal["USER", "GROUP", "ORGANIZATION"]


class KintoneAddComment(_Record):
    """Add a comment and optional user, group or organization mentions."""
    operation: Literal["add_comment"] = "add_comment"
    text: str = Field(..., min_length=1, max_length=65535)
    mentions: list[Mention] = Field(default_factory=list, max_length=10)


class KintoneDeleteComment(_Record):
    """Delete one comment by ID."""
    operation: Literal["delete_comment"] = "delete_comment"
    comment_id: int = Field(..., ge=1)


class KintoneCreateCursor(_App):
    """Create an export cursor. The query accepts conditions only, without order by, limit or offset."""
    operation: Literal["create_cursor"] = "create_cursor"
    query: str | None = Field(None, max_length=16384)
    fields: list[str] | None = Field(None, max_length=1000)
    size: int = Field(100, ge=1, le=500)


class KintoneGetCursor(_Input):
    """Read the next cursor page; repeat until next is false. Reading advances the cursor."""
    operation: Literal["get_cursor"] = "get_cursor"
    cursor_id: str = Field(..., min_length=1, max_length=256)


class KintoneDeleteCursor(KintoneGetCursor):
    """Delete an unfinished export cursor."""
    operation: Literal["delete_cursor"] = "delete_cursor"


class KintoneUpdateStatus(_Record):
    """Run a configured process action, optionally choosing the next assignee."""
    operation: Literal["update_status"] = "update_status"
    action: str = Field(..., min_length=1, max_length=1024)
    assignee: str | None = None
    revision: int | None = Field(None, ge=-1)


class KintoneUpdateAssignees(_Record):
    """Replace process assignees; an empty list clears them."""
    operation: Literal["update_assignees"] = "update_assignees"
    assignees: list[str] = Field(..., max_length=100)
    revision: int | None = Field(None, ge=-1)


class KintoneOnNewRecord(PollTriggerConfigBase):
    """Watch an app for new records. Existing records become the initial baseline.

    Polls all accessible records, up to 10,000; larger apps fail without advancing
    the baseline. The API token needs View records permission for this app.
    """
    operation: Literal["on_new_record"] = Field("on_new_record", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Record",
    })
    app_id: int = Field(..., ge=1, title="App ID", description="The app to watch. The API token must have View records permission for this app.")


class KintoneOnNewOrUpdatedRecord(KintoneOnNewRecord):
    """Watch for new records or changes to their accessible field values.

    Polling compares complete records between runs; intermediate edits between
    polls and changes to fields the token cannot view are not delivered.
    Supports apps with at most 10,000 accessible records.
    """
    operation: Literal["on_new_or_updated_record"] = Field("on_new_or_updated_record", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated Record",
    })


KintoneConfig = Annotated[Union[
    KintoneGetApp, KintoneGetFields, KintoneGetViews, KintoneGetProcess,
    KintoneGetRecord, KintoneListRecords, KintoneCreateRecord, KintoneUpdateRecord,
    KintoneCreateRecords, KintoneUpdateRecords, KintoneDeleteRecords,
    KintoneGetComments, KintoneAddComment, KintoneDeleteComment,
    KintoneCreateCursor, KintoneGetCursor, KintoneDeleteCursor,
    KintoneUpdateStatus, KintoneUpdateAssignees,
    KintoneOnNewRecord, KintoneOnNewOrUpdatedRecord,
], Field(discriminator="operation")]


class KintoneFullConfig(NodeConfig[KintoneConfig, KintoneAPITokenCredential]):
    pass


# Each operation is exactly one published REST operation, with no implicit writes.
ROUTES = {
    "get_app": ("GET", "app"),
    "get_fields": ("GET", "app/form/fields"),
    "get_views": ("GET", "app/views"),
    "get_process": ("GET", "app/status"),
    "get_record": ("GET", "record"),
    "list_records": ("GET", "records"),
    "create_record": ("POST", "record"),
    "update_record": ("PUT", "record"),
    "create_records": ("POST", "records"),
    "update_records": ("PUT", "records"),
    "delete_records": ("DELETE", "records"),
    "get_comments": ("GET", "record/comments"),
    "add_comment": ("POST", "record/comment"),
    "delete_comment": ("DELETE", "record/comment"),
    "create_cursor": ("POST", "records/cursor"),
    "get_cursor": ("GET", "records/cursor"),
    "delete_cursor": ("DELETE", "records/cursor"),
    "update_status": ("PUT", "record/status"),
    "update_assignees": ("PUT", "record/assignees"),
}


def _guard_credential(data):
    raw = data.get("credentials")
    if raw is not None and (not isinstance(raw, dict) or raw.get("credential_type") != "kintone_api_token"):
        raise ValueError("Attach a Kintone API token credential")


_POLL_PAGE_SIZE = 500
_POLL_MAX_RECORDS = 10_000


class KintoneNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-kintone"
    connection_evidence = ConnectionEvidence(noun="Kintone app", identity_operation="get_app")

    @classmethod
    def get_config_model(cls):
        return KintoneFullConfig

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

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Supply a Kintone API token credential")
        operation = config.operation
        if isinstance(config, KintoneOnNewRecord):
            return await self._poll_records(config)
        method, route = ROUTES[operation]
        params = {k: v for k, v in config.model_dump(exclude={"operation", "app_id"}).items() if v is not None}
        if operation == "update_records":
            params["records"] = [{k: v for k, v in row.items() if v is not None} for row in params["records"]]
        if isinstance(config, _App):
            params["app"] = config.app_id or credential.app_id
        if "record_id" in params:
            params["record" if operation in {"get_comments", "add_comment", "delete_comment"} else "id"] = params.pop("record_id")
        if operation == "get_app":
            params["id"] = params.pop("app")
        if "cursor_id" in params:
            params["id"] = params.pop("cursor_id")
        if operation == "list_records":
            params["totalCount"] = "true" if params.pop("total_count") else "false"
        if operation == "add_comment":
            params["comment"] = {"text": params.pop("text"), "mentions": params.pop("mentions")}
        if operation == "delete_comment":
            params["comment"] = params.pop("comment_id")
        return await self._request(operation, method, route, params)

    async def _request(self, operation, method, route, params):
        credential = self.config.credentials
        url = credential.tenant_url + "/k/v1/" + route + ".json"
        kwargs = {}
        if method == "GET":
            url += "?" + urlencode(params)
        else:
            kwargs["json"] = params
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, url, headers={"X-Cybozu-API-Token": credential.api_token, "Accept": "application/json"}, **kwargs)
            if len(response.content) > 8_000_000:
                raise ValueError("Kintone response exceeds the size limit")
            if response.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
                raise ValueError("Expected a JSON response from Kintone")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object from Kintone")
            if response.status_code != 200 or "code" in body and "message" in body:
                message = body.get("message") or f"Kintone returned HTTP {response.status_code}"
                # Error text can contain echoed request values. Never expose tokens.
                message = str(message)
                for token in [credential.api_token, *credential.api_token.split(",")]:
                    message = message.replace(token, "[redacted]")
                return {"status": "error", "error": message[:2000], "http_status": response.status_code}
            self._validate_response(operation, body)
            return {**body, "operation": operation, "status": "success"}
        except (httpx.HTTPError, SSRFError, ValueError):
            return {"status": "error", "error": "Kintone request failed or returned an invalid response"}

    async def _poll_records(self, config):
        # The published query grammar allows $id ordering/comparison. Keyset
        # pagination avoids offset drift if records are inserted/deleted mid-poll.
        records = []
        after = 0
        while True:
            body = await self._request("list_records", "GET", "records", {
                "app": config.app_id,
                "query": f"$id > {after} order by $id asc limit {_POLL_PAGE_SIZE}",
                "totalCount": "false",
            })
            if body.get("status") != "success":
                raise ValueError(body.get("error") or "Kintone poll failed")
            page = body["records"]
            for record in page:
                record_id = self._record_id(record)
                if int(record_id) <= after:
                    raise ValueError("Kintone records are missing their ordered IDs")
                after = int(record_id)
            records.extend(page)
            if len(records) > _POLL_MAX_RECORDS:
                raise ValueError("Kintone polling supports apps with at most 10,000 accessible records")
            if len(page) < _POLL_PAGE_SIZE:
                break

        def identity(record):
            record_id = self._record_id(record)
            if config.operation == "on_new_record":
                return record_id
            # Field codes are app-defined. Compare the entire documented record
            # object rather than assuming an English Updated_datetime field code.
            digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            return f"{record_id}:{digest}"

        fresh = await self._filter_unseen(records, identity)
        return {"status": "success", "operation": config.operation, "app_id": config.app_id,
                "tenant_url": self.config.credentials.tenant_url,
                "records": fresh, "record_count": len(fresh)}

    @staticmethod
    def _record_id(record):
        field = record.get("$id") if isinstance(record, dict) else None
        value = field.get("value") if isinstance(field, dict) else None
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
            raise ValueError("Kintone record is missing its numeric $id.value")
        return value

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_record", "on_new_or_updated_record"}:
            return bool(output.get("record_count"))
        return super().should_propagate_output(output, config)

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") not in {"on_new_record", "on_new_or_updated_record"}:
            return super().resolve_agent_event(output)
        records = output.get("records") or []
        if not records:
            return None
        change = "new" if output["operation"] == "on_new_record" else "new or updated"
        app_id, tenant = output["app_id"], output["tenant_url"]
        lines = [f"Kintone: {len(records)} {change} record(s) in app {app_id}."]
        for record in records[:10]:
            record_id = cls._record_id(record)
            # Keep app-defined field codes and values, including creator/modifier
            # identity, so the agent can understand the content and act on it.
            content = json.dumps(record, ensure_ascii=False)[:4000]
            lines.append(f"Record {record_id}: {tenant}/k/{app_id}/show#record={record_id}\n{content}")
        if len(records) > 10:
            lines.append(f"And {len(records) - 10} more; all records are in the trigger output.")
        return {"text": "\n".join(lines), "conversation_key": f"kintone:{tenant}:{app_id}"}

    @staticmethod
    def _validate_response(operation, body):
        shapes = {
            "get_app": {"appId": str, "name": str},
            "get_fields": {"properties": dict, "revision": str},
            "get_views": {"views": dict},
            "get_process": {},
            "get_record": {"record": dict},
            "list_records": {"records": list},
            "create_record": {"id": str, "revision": str},
            "update_record": {"revision": str},
            "create_records": {"ids": list, "revisions": list},
            "update_records": {"records": list},
            "delete_records": {},
            "get_comments": {"comments": list, "newer": bool, "older": bool},
            "add_comment": {"id": str},
            "delete_comment": {},
            "create_cursor": {"id": str},
            "get_cursor": {"records": list, "next": bool},
            "delete_cursor": {},
            "update_status": {},
            "update_assignees": {},
        }
        if "error" in body or "errors" in body:
            raise ValueError("Kintone error envelope")
        if any(not isinstance(body.get(key), kind) for key, kind in shapes[operation].items()):
            raise ValueError("Kintone response is missing required fields")

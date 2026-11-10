"""TheHive v1 incident response API, pinned to StrangeBee's v6.0.0 contract.

Reference: https://docs.strangebee.com/thehive/api-docs/docs.yaml
Query syntax: https://docs.strangebee.com/thehive/user-guides/query-syntax/
Notifications have no documented API registration, so the trigger polls the latest audit feed.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

DOCS = "https://docs.strangebee.com/thehive/api-docs/"


class TheHiveApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="TheHive API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.strangebee.com/thehive/user-guides/manage-user-settings/#manage-your-api-key",
                           "x-credential-instructions": "In TheHive, open your user settings and copy your API key. Enter your instance origin and paste the key below."})
    credential_type: Literal["thehive_api_key"] = Field("thehive_api_key", json_schema_extra={"ui:hidden": True})
    base_url: str = Field(..., title="Instance URL", description="Public HTTPS origin of your TheHive instance, for example https://thehive.example.com. Use an instance reachable from NoClick.")
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"}, description="Paste your existing API key without the Bearer prefix.")
    organisation: str | None = Field(None, title="Organization", max_length=128, description="Optional organization name for X-Organisation. Leave blank to use your default organization.")

    @field_validator("base_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value, field_name="Instance URL")
        if not origin.startswith("https://"):
            raise ValueError("Use the public HTTPS origin of your TheHive instance")
        return origin

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if not value or any(c.isspace() for c in value) or len(value) > 4096:
            raise ValueError("Paste just the API key without a header or whitespace")
        return value

    @field_validator("organisation")
    @classmethod
    def organization_header(cls, value):
        if value is None:
            return None
        value = value.strip()
        if any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Organization must be a single ASCII header value")
        return value or None


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _text(title, *, required=False, maximum=1048576, description=None):
    return (str if required else str | None, Field(... if required else None, title=title,
        min_length=1, max_length=maximum, description=description))


def _identifier(title):
    return _text(title, required=True, maximum=512,
        description="Copy the entity ID (including its ~ prefix) from TheHive. Cases also accept a case number.")


# Each entry makes exactly one call to the named operation in the published contract.
# Body names use the API's spelling; unset fields are omitted, including PATCH fields.
OPERATIONS = {
    "get_current_user": ("GET", "/api/v1/user/current", (), "Get Current User"),
    "get_activity": ("GET", "/api/v1/flow", (), "Get Recent Activity"),
    "list_cases": ("POST", "/api/v1/query", (), "List Cases"),
    "get_case": ("GET", "/api/v1/case/{case_id}", (), "Get Case"),
    "create_case": ("POST", "/api/v1/case", ("title", "description", "severity", "tags", "tlp", "pap", "assignee", "caseTemplate"), "Create Case"),
    "update_case": ("PATCH", "/api/v1/case/{case_id}", ("title", "description", "severity", "tags", "status", "summary", "assignee", "tlp", "pap", "addTags", "removeTags"), "Update Case"),
    "list_alerts": ("POST", "/api/v1/query", (), "List Alerts"),
    "get_alert": ("GET", "/api/v1/alert/{alert_id}", (), "Get Alert"),
    "create_alert": ("POST", "/api/v1/alert", ("type", "source", "sourceRef", "title", "description", "severity", "tags", "tlp", "pap", "date", "assignee"), "Create Alert"),
    "update_alert": ("PATCH", "/api/v1/alert/{alert_id}", ("title", "description", "severity", "tags", "status", "summary", "assignee", "tlp", "pap", "addTags", "removeTags"), "Update Alert"),
    "promote_alert": ("POST", "/api/v1/alert/{alert_id}/case", ("title", "description", "caseTemplate", "assignee"), "Create Case from Alert"),
    "list_tasks": ("POST", "/api/v1/query", (), "List Tasks"),
    "get_task": ("GET", "/api/v1/task/{task_id}", (), "Get Task"),
    "create_task": ("POST", "/api/v1/case/{case_id}/task", ("title", "description", "status", "assignee", "dueDate", "group"), "Create Task"),
    "update_task": ("PATCH", "/api/v1/task/{task_id}", ("title", "description", "status", "assignee", "dueDate", "group"), "Update Task"),
    "create_task_log": ("POST", "/api/v1/task/{task_id}/log", ("message", "startDate"), "Create Task Log"),
    "list_observables": ("POST", "/api/v1/query", (), "List Observables"),
    "get_observable": ("GET", "/api/v1/observable/{observable_id}", (), "Get Observable"),
    "create_case_observable": ("POST", "/api/v1/case/{case_id}/observable", ("dataType", "data", "message", "tlp", "pap", "tags", "ioc", "sighted"), "Add Case Observable"),
    "update_observable": ("PATCH", "/api/v1/observable/{observable_id}", ("message", "tlp", "pap", "tags", "ioc", "sighted", "ignoreSimilarity"), "Update Observable"),
    "create_case_comment": ("POST", "/api/v1/case/{case_id}/comment", ("message",), "Add Case Comment"),
    "create_alert_comment": ("POST", "/api/v1/alert/{alert_id}/comment", ("message",), "Add Alert Comment"),
}
LISTS = {"list_cases": "listCase", "list_alerts": "listAlert", "list_tasks": "listTask", "list_observables": "listObservable"}
REQUIRED = {"create_case": {"title", "description"}, "create_alert": {"type", "source", "sourceRef", "title", "description"},
            "create_task": {"title"}, "create_task_log": {"message"}, "create_case_observable": {"dataType", "data"},
            "create_case_comment": {"message"}, "create_alert_comment": {"message"}}


def _body_field(name, required):
    if name in {"tags", "addTags", "removeTags"}:
        return (list[Annotated[str, Field(min_length=1, max_length=128)]] | None, Field(None, title=name, max_length=1000))
    if name in {"severity", "tlp", "pap"}:
        values = {"severity": (1, 2, 3, 4), "tlp": (0, 1, 2, 3, 4), "pap": (0, 1, 2, 3)}[name]
        return (Literal[values] | None, Field(None, title=name.upper() if name != "severity" else "Severity"))
    if name in {"dueDate", "startDate", "date"}:
        return (int | None, Field(None, ge=0, description="Unix timestamp in milliseconds"))
    if name in {"ioc", "sighted", "ignoreSimilarity"}:
        return (bool | None, Field(None, title=name))
    limit = {"title": 512, "status": 64, "source": 128, "sourceRef": 128, "type": 128,
             "dataType": 128, "assignee": 128, "caseTemplate": 128, "data": 4096}.get(name, 1048576)
    return _text(name, required=required, maximum=limit)


def _model(name, spec):
    method, path, body, label = spec
    fields = {"operation": (Literal[name], Field(name, title=label,
        json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-is-trigger": False}))}
    for identifier in ("case_id", "alert_id", "task_id", "observable_id"):
        if "{" + identifier + "}" in path:
            fields[identifier] = _identifier(identifier.replace("_", " ").title())
    if name == "get_activity":
        fields.update(count=(int, Field(100, ge=1, le=1000, title="Recent Entries")), root_id=(str | None, Field(None, title="Case ID", description="Optional case ID including ~. Case numbers are not accepted by the audit feed.")))
    if name in LISTS:
        fields.update(offset=(int, Field(0, ge=0, le=1000000, title="Offset")),
                      limit=(int, Field(100, ge=1, le=100, title="Page Size")),
                      created_since=(int | None, Field(None, ge=0, title="Created Since", description="Inclusive Unix timestamp in milliseconds")))
    for field in body:
        fields[field] = _body_field(field, field in REQUIRED.get(name, set()))
    return create_model("TheHive" + "".join(word.title() for word in name.split("_")) + "Config", __base__=_Input, **fields)


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class TheHiveOnNewActivityConfig(PollTriggerConfigBase):
    operation: Literal["on_new_activity"] = Field("on_new_activity", title="On New or Updated Activity", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated Activity"})
    root_id: str | None = Field(None, title="Case ID", description="Optional case ID including ~ to watch a case and its linked objects. Leave blank for all visible activity.")
    count: int = Field(100, ge=1, le=1000, title="Recent Entries", description="Number of most recent audit entries to inspect each poll. Poll frequently enough to keep changes within this window. Existing entries are baselined when armed.")


TheHiveConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (TheHiveOnNewActivityConfig,)], Field(discriminator="operation")]


class TheHiveNodeConfig(NodeConfig[TheHiveConfig, TheHiveApiKeyCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


class TheHiveNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-thehive"
    connection_evidence = ConnectionEvidence(identity_operation="get_current_user", identity_keys=("name", "login", "organisation"), noun="account")
    edit_examples = ["Create a case from an alert", "Add an observable to this case", "Watch for case and alert activity", "Update a task and add an investigation log"]

    @classmethod
    def get_config_model(cls):
        return TheHiveNodeConfig

    @staticmethod
    async def _request(credential, method, path, body=None, *, params=None):
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        if credential.organisation:
            headers["X-Organisation"] = credential.organisation
        async with guarded_async_client(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, credential.base_url + path, headers=headers, json=body, params=params)
        if response.status_code >= 300:
            try:
                payload = response.json()
                detail = payload.get("message") if isinstance(payload, dict) else None
            except ValueError:
                detail = None
            raise ValueError(_redact(f"TheHive API error {response.status_code}: {detail or 'request failed'}", credential.api_key))
        if response.status_code == 204:
            return {"acknowledged": True}
        try:
            return response.json()
        except ValueError:
            raise ValueError("TheHive returned an invalid JSON response") from None

    @classmethod
    async def _list(cls, credential, entity, *, offset=0, limit=100, created_since=None):
        query = [{"_name": entity}]
        if created_since is not None:
            query.append({"_name": "filter", "_gte": {"_field": "_createdAt", "_value": created_since}})
        query.extend([{"_name": "sort", "_fields": [{"_createdAt": "desc"}]},
                      {"_name": "page", "from": offset, "to": offset + limit}])
        rows = await cls._request(credential, "POST", "/api/v1/query", {"query": query})
        if not isinstance(rows, list) or len(rows) > limit or any(not isinstance(row, dict) for row in rows):
            raise ValueError("TheHive query did not return an entity array within the requested page size")
        return rows

    @classmethod
    async def _activity(cls, credential, operation):
        params = {"count": operation.count}
        if operation.root_id:
            params["rootId"] = operation.root_id
        rows = await cls._request(credential, "GET", "/api/v1/flow", params=params)
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("base"), dict) for row in rows):
            raise ValueError("TheHive activity feed did not return an audit array")
        return rows

    async def _poll(self, credential, operation):
        rows = await self._activity(credential, operation)
        ids = [row["base"].get("_id") for row in rows]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("TheHive poll returned missing or repeated audit IDs; retry the poll")
        fresh = await self._filter_unseen(rows, lambda row: row["base"]["_id"])
        return {"items": fresh, "new_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_count")) if config.get("operation") == "on_new_activity" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "items" not in output:
            return super().resolve_agent_event(output)
        rows = output["items"]
        if not rows:
            return None
        import json
        lines = []
        for row in rows[:10]:
            audit = row["base"]
            lines.append(f"- {audit.get('_createdBy') or 'Unknown user'}: {audit.get('action') or 'change'} "
                         f"{audit.get('objectType') or 'entity'} {audit.get('objectId') or audit.get('rootId')}; "
                         f"parent {audit.get('rootId')}, audit {audit['_id']}, at {audit.get('_createdAt')}: "
                         + json.dumps(audit.get('details') or {}, ensure_ascii=False))
        if len(rows) > 10:
            lines.append(f"- {len(rows) - 10} more; full audit entries are in items")
        return {"text": f"TheHive: {len(rows)} new activity entries:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a TheHive API key")
        credential, op = self.config.credentials, self.config.config
        name = op.operation
        if isinstance(op, TheHiveOnNewActivityConfig):
            return _redact(await self._poll(credential, op), credential.api_key)
        if name == "get_activity":
            return {"data": _redact(await self._activity(credential, op), credential.api_key)}
        if name in LISTS:
            rows = await self._list(credential, LISTS[name], offset=op.offset, limit=op.limit, created_since=op.created_since)
            return _redact({"data": rows, "next_offset": op.offset + op.limit if len(rows) == op.limit else None}, credential.api_key)
        method, path, body_fields, _ = OPERATIONS[name]
        values = op.model_dump(exclude_none=True)
        for field, value in values.items():
            path = path.replace("{" + field + "}", quote(str(value), safe=""))
        body = {field: values[field] for field in body_fields if field in values} if method in {"POST", "PATCH"} else None
        if method == "PATCH" and not body:
            raise ValueError("Provide at least one field to update")
        data = await self._request(credential, method, path, body)
        if name == "create_case_observable":
            if not isinstance(data, list):
                raise ValueError("TheHive did not return an observable array")
        elif not isinstance(data, dict):
            raise ValueError("TheHive did not return an entity object")
        return {"data": _redact(data, credential.api_key)}

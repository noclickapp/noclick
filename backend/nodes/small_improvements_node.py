"""Small Improvements REST API v2, using personal access tokens.

Contract: https://storage.googleapis.com/si-rest-api-docs/dist/swagger.json (1.0).
Auth/regions: https://resources.small-improvements.com/knowledge-base/small-improvements-rest-api/
The provider publishes opaque DTO schemas. Return those objects intact rather
than depending on undocumented fields. Body-based DTO mutations are omitted.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

AUTH_DOCS = "https://resources.small-improvements.com/knowledge-base/small-improvements-rest-api/"
TYPE = "small_improvements_personal_access_token"


class SmallImprovementsPersonalAccessToken(BaseModel):
    model_config = ConfigDict(title="Small Improvements Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOCS,
            "x-credential-instructions": "Ask Small Improvements to enable API access for your company. Then open Profile → Manage → API Access Tokens and create a token. Paste it here and select your company's data center. The token has the permissions of its employee account."})
    credential_type: Literal["small_improvements_personal_access_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Personal access token", min_length=1, max_length=4096,
                              json_schema_extra={"ui:widget": "password"})
    data_center: Literal["app", "eu"] = Field("app", title="Data center",
        description="Choose app for the US data center or eu for the EU data center.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the token without an Authorization or Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def safe_values(cls, value, info):
        if value is None:
            return value
        if info.field_name in {"user_id", "manager_id", "reviewer_id", "cycle_id", "objective_id",
                               "praise_id", "comment_id", "author_id", "recipient_id"} and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
            raise ValueError("Use a single Small Improvements resource ID")
        if info.field_name in {"start_date", "end_date"}:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an ISO 8601 date-time with a timezone") from None
        return value


# One outgoing API operation per catalog operation. Parameter names on the wire
# are deliberately explicit; no arbitrary endpoint or extra-parameter escape.
OPERATIONS = {
    "get_current_user": ("GET", "/v2/users/me", {}),
    "list_users": ("GET", "/v2/users", {"manager_id": "managerId", "include_guests": "includeGuests", "show_locked": "showLocked"}),
    "get_user": ("GET", "/v2/users/{user_id}", {}),
    "search_users": ("GET", "/v2/users/search", {"email": "email"}),
    "set_manager": ("PUT", "/v2/users/{user_id}/manager", {"manager_id": "managerId"}),
    "set_secondary_reviewer": ("PUT", "/v2/users/{user_id}/secondary-reviewer", {"reviewer_id": "secondaryReviewerId"}),
    "lock_users": ("POST", "/v2/users/roles/lock", {}),
    "unlock_users": ("POST", "/v2/users/roles/unlock", {}),
    "list_praise": ("GET", "/v2/praise", {"author_id": "authorId", "recipient_id": "recipientId", "start_date": "startDate", "end_date": "endDate", "limit": "limit", "offset": "offset"}),
    "get_praise": ("GET", "/v2/praise/{praise_id}", {}),
    "delete_praise": ("DELETE", "/v2/praise/{praise_id}", {}),
    "list_praise_comments": ("GET", "/v2/praise/{praise_id}/comments", {}),
    "delete_praise_comment": ("DELETE", "/v2/praise/{praise_id}/comments/{comment_id}", {}),
    "list_objective_cycles": ("GET", "/v2/objective-cycles", {}),
    "get_objective_cycle": ("GET", "/v2/objective-cycles/{cycle_id}", {}),
    "list_objectives": ("GET", "/v2/objective-cycles/{cycle_id}/objectives", {"user_id": "userId"}),
    "get_objective": ("GET", "/v2/objective-cycles/{cycle_id}/objectives/{objective_id}", {}),
    "set_objective_completion": ("POST", "/v2/objective-cycles/{cycle_id}/objectives/{objective_id}/changeCompletionPercentage", {"completion_percentage": "completionPercentage"}),
    "delete_objective": ("DELETE", "/v2/objective-cycles/{cycle_id}/objectives/{objective_id}", {}),
    "archive_objective_cycle": ("PUT", "/v2/objective-cycles/{cycle_id}/archive", {}),
    "unarchive_objective_cycle": ("PUT", "/v2/objective-cycles/{cycle_id}/unarchive", {}),
    "list_review_cycles": ("GET", "/v2/review-cycles", {"only_manageable": "onlyManageable"}),
    "list_reviews": ("GET", "/v2/review-cycles/{cycle_id}/reviews", {"manager_id": "managerId"}),
}


def _field(name, required):
    if name in {"start_date", "end_date"}:
        return (str | None, Field(None, json_schema_extra={"format": "date-time"}))
    if name in {"include_guests", "show_locked", "only_manageable"}:
        return (bool | None, Field(None))
    if name in {"limit", "offset", "completion_percentage"}:
        return (int, Field(... if required else 100 if name == "limit" else 0,
                           ge=0 if name != "limit" else 1, le=100 if name != "offset" else 1_000_000))
    if name == "user_ids":
        return (list[str], Field(..., min_length=1, max_length=100,
            description="Employee IDs to lock or unlock.", json_schema_extra={"ui:widget": "list"}))
    return (str if required else str | None, Field(... if required else None, min_length=1, max_length=500))


def _make_config(name, spec):
    _, path, query = spec
    required = set(re.findall(r"\{(\w+)\}", path))
    if name == "set_manager": required.add("manager_id")
    if name == "set_secondary_reviewer": required.add("reviewer_id")
    if name == "set_objective_completion": required.add("completion_percentage")
    if name == "search_users": required.add("email")
    if name in {"lock_users", "unlock_users"}: required.add("user_ids")
    label = name.replace("_", " ").title()
    return create_model("SmallImprovements" + name.title().replace("_", "") + "Config", __base__=_Input,
        __module__=__name__, operation=(Literal[name], Field(name, title=label,
            json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-is-trigger": False})),
        **{key: _field(key, key in required) for key in sorted(required | set(query))})


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class SmallImprovementsOnNewOrChangedPraise(PollTriggerConfigBase, _Input):
    """Compare complete praise records, without assuming undocumented DTO fields.

    Polls the date window in full. A record emits once per distinct JSON value;
    reverting to an already seen value does not emit again. No hard deletes.
    """
    model_config = ConfigDict(extra="ignore", json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_new_or_changed_praise"] = Field("on_new_or_changed_praise",
        title="On New or Changed Praise", json_schema_extra={"ui:hidden": True, "x-is-trigger": True,
            "x-display-name": "On New or Changed Praise"})
    start_date: str | None = Field(None, description="Optional ISO 8601 startDate for the monitored window, with timezone.",
                                  json_schema_extra={"format": "date-time"})
    author_id: str | None = None
    recipient_id: str | None = None


SmallImprovementsConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (SmallImprovementsOnNewOrChangedPraise,)], Field(discriminator="operation")]


class SmallImprovementsNodeConfig(NodeConfig[SmallImprovementsConfig, SmallImprovementsPersonalAccessToken]):
    pass


class SmallImprovementsNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-small-improvements"
    connection_evidence = ConnectionEvidence(noun="employee account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return SmallImprovementsNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        url = f"https://{credential.data_center}.small-improvements.com/api{path}"
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, url, params=params,
                headers={"Authorization": f"Bearer {credential.access_token}",
                         "Accept": "application/json;charset=UTF-8",
                         **({"Content-Type": "application/json;charset=UTF-8"} if body is not None else {})},
                **({"json": body} if body is not None else {}))
        if response.status_code >= 300:
            # Provider text is useful on connect, but must never echo the token.
            detail = response.text.replace(credential.access_token, "[redacted]")[:2000]
            raise ValueError(f"Small Improvements API {response.status_code}: {detail}")
        if not response.content:
            return None
        return response.json()

    async def execute(self, inputs):
        op, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a Small Improvements personal access token")
        if isinstance(op, SmallImprovementsOnNewOrChangedPraise):
            rows = []
            params = {key: value for key, value in {"startDate": op.start_date,
                "authorId": op.author_id, "recipientId": op.recipient_id}.items() if value is not None}
            # Read the complete bounded window before advancing the seen set.
            for offset in range(0, 10000, 100):
                page = await self._request(credential, "GET", "/v2/praise", params={**params, "limit": 100, "offset": offset})
                if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                    raise ValueError("Small Improvements praise must be an array of objects")
                rows.extend(page)
                if len(page) < 100:
                    break
            else:
                raise ValueError("Praise window exceeds 10,000 records; narrow the start date or employee filters")
            fresh = await self._filter_unseen(rows, lambda row: hashlib.sha256(
                json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
            output = {"praise": fresh, "new_or_changed_count": len(fresh)}
        else:
            method, path, query = OPERATIONS[op.operation]
            values = op.model_dump(exclude_none=True)
            for name in re.findall(r"\{(\w+)\}", path):
                path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
            params = {wire: values[name] for name, wire in query.items() if name in values}
            body = values.get("user_ids")
            output = {"data": await self._request(credential, method, path, params=params, body=body)}
        await self.emit(output)
        return output

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_or_changed_count")) if config.get("operation") == "on_new_or_changed_praise" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "praise" not in output:
            return super().resolve_agent_event(output)
        rows = output["praise"]
        if not rows:
            return None
        return {"text": f"Small Improvements: {len(rows)} new or changed praise record(s). "
                "The complete provider records follow, including any employee and praise identifiers returned by the API:\n"
                + json.dumps(rows, ensure_ascii=False), "conversation_key": None}

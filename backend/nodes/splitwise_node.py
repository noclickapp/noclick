"""Splitwise API v3: personal bearer-key operations against the published contract."""
from __future__ import annotations

from datetime import datetime
from html import unescape
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://secure.splitwise.com/api/v3.0"


class SplitwiseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Splitwise API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://secure.splitwise.com/apps",
            "x-credential-instructions": "Open your registered app in Splitwise's developer settings and generate a personal API key. Paste the key alone. It grants access to your personal Splitwise account and is sent as a Bearer token to secure.splitwise.com. Connecting reads your current user; it does not verify every write permission.",
        })
    credential_type: Literal["splitwise_api_key"] = Field("splitwise_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key alone without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


ResourceID = Annotated[int, Field(gt=0)]
GroupID = Annotated[int, Field(ge=0)]
Text = Annotated[str, Field(min_length=1, max_length=5000)]
Money = Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]{1,2})?$")]


class _ExpenseFields(_Input):
    cost: Money = Field(..., description="Decimal cost as a string, with at most two decimal places.")
    description: Text
    details: str | None = Field(None, max_length=10000)
    date: datetime | None = None
    currency_code: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    category_id: ResourceID | None = None
    repeat_interval: Literal["never", "weekly", "fortnightly", "monthly", "yearly"] | None = None


class SplitwiseGetCurrentUserConfig(_Input):
    """Get the authenticated Splitwise user."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class SplitwiseGetUserConfig(_Input):
    """Get a user by ID."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseGetGroupsConfig(_Input):
    """List groups for the current user."""
    operation: Literal["get_groups"] = Field("get_groups", json_schema_extra={"ui:hidden": True})


class SplitwiseGetGroupConfig(_Input):
    """Get a group and its balances."""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseCreateGroupConfig(_Input):
    """Create a group containing the current user."""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: Text
    group_type: Literal["home", "trip", "couple", "other", "apartment", "house"] | None = None
    simplify_by_default: bool | None = None


class SplitwiseDeleteGroupConfig(_Input):
    """Delete a group and all its associated expenses."""
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseAddUserToGroupConfig(_Input):
    """Add an existing Splitwise user to a group."""
    operation: Literal["add_user_to_group"] = Field("add_user_to_group", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID
    user_id: ResourceID


class SplitwiseRemoveUserFromGroupConfig(_Input):
    """Remove a group member with a zero balance."""
    operation: Literal["remove_user_from_group"] = Field("remove_user_from_group", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID
    user_id: ResourceID


class SplitwiseGetFriendsConfig(_Input):
    """List friends and balances."""
    operation: Literal["get_friends"] = Field("get_friends", json_schema_extra={"ui:hidden": True})


class SplitwiseGetFriendConfig(_Input):
    """Get one friend and balances."""
    operation: Literal["get_friend"] = Field("get_friend", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseDeleteFriendConfig(_Input):
    """Remove a friendship."""
    operation: Literal["delete_friend"] = Field("delete_friend", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseGetExpensesConfig(_Input):
    """List one expense page; increase offset to retrieve subsequent pages."""
    operation: Literal["get_expenses"] = Field("get_expenses", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID | None = None
    friend_id: ResourceID | None = None
    dated_after: datetime | None = None
    dated_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


class SplitwiseGetExpenseConfig(_Input):
    """Get a single expense."""
    operation: Literal["get_expense"] = Field("get_expense", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseCreateExpenseConfig(_ExpenseFields):
    """Create an expense split equally in a group; the current user pays."""
    operation: Literal["create_expense"] = Field("create_expense", json_schema_extra={"ui:hidden": True})
    group_id: ResourceID
    split_equally: Literal[True] = True


class SplitwiseUpdateExpenseConfig(_ExpenseFields):
    """Update expense fields while preserving existing participant shares."""
    operation: Literal["update_expense"] = Field("update_expense", json_schema_extra={"ui:hidden": True})
    id: ResourceID
    group_id: GroupID = Field(..., description="Use 0 for an expense outside a group. Existing shares are preserved; no participant share fields are sent.")


class SplitwiseDeleteExpenseConfig(_Input):
    """Delete an expense."""
    operation: Literal["delete_expense"] = Field("delete_expense", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseUndeleteExpenseConfig(_Input):
    """Restore a deleted expense."""
    operation: Literal["undelete_expense"] = Field("undelete_expense", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseGetCommentsConfig(_Input):
    """List the comments on an expense."""
    operation: Literal["get_comments"] = Field("get_comments", json_schema_extra={"ui:hidden": True})
    expense_id: ResourceID


class SplitwiseCreateCommentConfig(_Input):
    """Comment on an expense."""
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={"ui:hidden": True})
    expense_id: ResourceID
    content: Text


class SplitwiseDeleteCommentConfig(_Input):
    """Delete a comment and return its record."""
    operation: Literal["delete_comment"] = Field("delete_comment", json_schema_extra={"ui:hidden": True})
    id: ResourceID


class SplitwiseGetNotificationsConfig(_Input):
    """Read recent activity; the provider may cap the returned list."""
    operation: Literal["get_notifications"] = Field("get_notifications", json_schema_extra={"ui:hidden": True})
    updated_after: datetime | None = None
    limit: int = Field(20, ge=1, le=100)


class SplitwiseGetCurrenciesConfig(_Input):
    """List the supported currencies."""
    operation: Literal["get_currencies"] = Field("get_currencies", json_schema_extra={"ui:hidden": True})


class SplitwiseGetCategoriesConfig(_Input):
    """List the supported expense categories."""
    operation: Literal["get_categories"] = Field("get_categories", json_schema_extra={"ui:hidden": True})


class SplitwiseOnExpenseChangedConfig(PollTriggerConfigBase):
    """Watch new or updated expenses; existing expenses are baselined when armed."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_expense_changed"] = Field("on_expense_changed", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "On New or Updated Expense",
    })
    group_id: ResourceID | None = None
    friend_id: ResourceID | None = Field(None, description="Ignored by Splitwise when a group is selected.")
    updated_after: datetime | None = Field(None, description="Optional start of the watched update window. Narrow this or select a group for accounts with more than 2,000 expenses.")


class SplitwiseOnNewActivityConfig(PollTriggerConfigBase):
    """Watch recent account activity, including comments, payments and group changes."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_new_activity"] = Field("on_new_activity", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "On New Activity",
    })
    updated_after: datetime | None = Field(None, description="Optional start of the activity window. Splitwise caps recent activity, so changes beyond its retained window cannot be detected.")


SplitwiseConfig = Annotated[Union[
    SplitwiseOnExpenseChangedConfig,
    SplitwiseOnNewActivityConfig,
    SplitwiseGetCurrentUserConfig,
    SplitwiseGetUserConfig,
    SplitwiseGetGroupsConfig,
    SplitwiseGetGroupConfig,
    SplitwiseCreateGroupConfig,
    SplitwiseDeleteGroupConfig,
    SplitwiseAddUserToGroupConfig,
    SplitwiseRemoveUserFromGroupConfig,
    SplitwiseGetFriendsConfig,
    SplitwiseGetFriendConfig,
    SplitwiseDeleteFriendConfig,
    SplitwiseGetExpensesConfig,
    SplitwiseGetExpenseConfig,
    SplitwiseCreateExpenseConfig,
    SplitwiseUpdateExpenseConfig,
    SplitwiseDeleteExpenseConfig,
    SplitwiseUndeleteExpenseConfig,
    SplitwiseGetCommentsConfig,
    SplitwiseCreateCommentConfig,
    SplitwiseDeleteCommentConfig,
    SplitwiseGetNotificationsConfig,
    SplitwiseGetCurrenciesConfig,
    SplitwiseGetCategoriesConfig
], Field(discriminator="operation")]


class SplitwiseFullConfig(NodeConfig[SplitwiseConfig, SplitwiseAPIKeyCredential]):
    pass


OPERATIONS = {
    'get_current_user': ('GET', '/get_current_user', 'user'),
    'get_user': ('GET', '/get_user/{id}', 'user'),
    'get_groups': ('GET', '/get_groups', 'groups'),
    'get_group': ('GET', '/get_group/{id}', 'group'),
    'create_group': ('POST', '/create_group', 'group'),
    'delete_group': ('POST', '/delete_group/{id}', 'success'),
    'add_user_to_group': ('POST', '/add_user_to_group', 'success'),
    'remove_user_from_group': ('POST', '/remove_user_from_group', 'success'),
    'get_friends': ('GET', '/get_friends', 'friends'),
    'get_friend': ('GET', '/get_friend/{id}', 'friend'),
    'delete_friend': ('POST', '/delete_friend/{id}', 'success'),
    'get_expenses': ('GET', '/get_expenses', 'expenses'),
    'get_expense': ('GET', '/get_expense/{id}', 'expense'),
    'create_expense': ('POST', '/create_expense', 'expenses'),
    'update_expense': ('POST', '/update_expense/{id}', 'expenses'),
    'delete_expense': ('POST', '/delete_expense/{id}', 'success'),
    'undelete_expense': ('POST', '/undelete_expense/{id}', 'success'),
    'get_comments': ('GET', '/get_comments', 'comments'),
    'create_comment': ('POST', '/create_comment', 'comment'),
    'delete_comment': ('POST', '/delete_comment/{id}', 'comment'),
    'get_notifications': ('GET', '/get_notifications', 'notifications'),
    'get_currencies': ('GET', '/get_currencies', 'currencies'),
    'get_categories': ('GET', '/get_categories', 'categories'),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class SplitwiseNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-splitwise"
    connection_evidence = ConnectionEvidence(noun="Splitwise account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return SplitwiseFullConfig

    @classmethod
    def resolve_agent_event(cls, output):
        if output.get("operation") not in {"on_expense_changed", "on_new_activity"}:
            return super().resolve_agent_event(output)
        expenses = output.get("expenses", [])
        activity = output.get("notifications", [])
        if not expenses and not activity:
            return None
        lines = []
        for expense in expenses[:10]:
            actor = expense.get("updated_by") or expense.get("created_by") or {}
            who = " ".join(str(actor.get(k) or "") for k in ("first_name", "last_name")).strip()
            lines.append(f"- {who or 'A Splitwise user'}: {expense.get('description') or 'Expense'}; "
                         f"{expense.get('cost')} {expense.get('currency_code')}; "
                         f"expense {expense.get('id')}, group {expense.get('group_id')}; "
                         f"updated {expense.get('updated_at')}. {expense.get('details') or ''}")
        for item in activity[:10]:
            source = item.get("source") or {}
            content = unescape(re.sub(r"<[^>]+>", " ", item.get("content") or "")).strip()
            lines.append(f"- User {item.get('created_by')}: {content}; activity {item.get('id')} "
                         f"at {item.get('created_at')}; {source.get('type') or 'account'} "
                         f"{source.get('id')}; {source.get('url') or ''}")
        count = len(expenses) + len(activity)
        if count > 10:
            lines.append(f"- … and {count - 10} more (full records in the trigger output)")
        return {"text": f"Splitwise: {count} expense change(s) or new activity item(s):\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_changes(self, config, key):
        expense_poll = isinstance(config, SplitwiseOnExpenseChangedConfig)
        path, envelope = ("/get_expenses", "expenses") if expense_poll else ("/get_notifications", "notifications")
        # Only declared provider fields leave the node; cron mirrors stay local.
        params = {"updated_after": config.updated_after.isoformat().replace("+00:00", "Z")} if config.updated_after else {}
        if expense_poll:
            params.update({name: getattr(config, name) for name in ("group_id", "friend_id")
                           if getattr(config, name) is not None})
        params["limit"] = 100 if expense_poll else 0
        items = []
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            for offset in range(0, 2000, 100):
                if expense_poll:
                    params["offset"] = offset
                response = await client.get(BASE + path, params=params,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
                if not 200 <= response.status_code < 300:
                    raise ValueError(f"Splitwise poll failed (HTTP {response.status_code})")
                if len(response.content) > 5_000_000:
                    raise ValueError("Splitwise poll response exceeds the read bound")
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get(envelope), list):
                    raise ValueError("Splitwise returned an invalid poll response")
                page = body[envelope]
                for item in page:
                    if not isinstance(item, dict) or type(item.get("id")) is not int:
                        raise ValueError("Splitwise poll item has no identity")
                    if expense_poll and not item.get("updated_at"):
                        raise ValueError("Splitwise expense has no update timestamp")
                items.extend(page)
                if not expense_poll or len(page) < 100:
                    break
                if offset == 1900:
                    raise ValueError("Splitwise poll exceeds 2,000 expenses; select a group, friend or later update window")
        fresh = await self._filter_unseen(items, lambda item:
            f"{item['id']}:{item['updated_at']}" if expense_poll else str(item["id"]))
        output = {"status": "success", "operation": config.operation,
                  envelope: _redact(fresh, key), "new_item_count": len(fresh)}
        await self.emit(output)
        return output

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Splitwise API key")
        config = self.config.config
        key = self.config.credentials.api_key
        if isinstance(config, (SplitwiseOnExpenseChangedConfig, SplitwiseOnNewActivityConfig)):
            return await self._poll_changes(config, key)
        method, path, envelope = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        kwargs = {"params": values} if method == "GET" else {"json": values} if values else {}
        write = method != "GET"
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            return {"status": "unknown" if write else "error", "operation": config.operation,
                "error": "Splitwise did not confirm the response; inspect the account before retrying a write.",
                "write_outcome": "unverified" if write else None}
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the shared credential-connect seam.
            return {"status": "error", "operation": config.operation, "http_status": response.status_code,
                "error": _redact(response.text[:4000], key)}
        try:
            if len(response.content) > 5_000_000:
                raise ValueError("Response exceeds the read bound")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Expected a Splitwise response object")
            if body.get("errors"):
                return {"status": "error", "operation": config.operation, "http_status": response.status_code,
                    "error": _redact(body["errors"], key)}
            if envelope == "success":
                if body.get("success") is not True:
                    raise ValueError("Splitwise did not acknowledge the change")
            else:
                result = body.get(envelope)
                plural = envelope in {"groups", "friends", "expenses", "comments", "notifications", "currencies", "categories"}
                if not isinstance(result, list if plural else dict):
                    raise ValueError("Expected the documented Splitwise response envelope")
                if config.operation in {"create_expense", "update_expense"}:
                    if "errors" not in body or not result:
                        raise ValueError("Splitwise did not acknowledge the expense write")
                if config.operation == "get_current_user" and (type(result.get("id")) is not int or result["id"] <= 0):
                    raise ValueError("Splitwise did not return an account identity")
            output = {"status": "success", "operation": config.operation, "http_status": response.status_code,
                **_redact(body, key)}
            if config.operation == "get_expenses":
                # Splitwise has offset pagination but no total/next link. A full
                # page is only a hint; callers can request the next offset.
                count = len(body["expenses"])
                output.update(offset=config.offset, limit=config.limit,
                    next_offset=config.offset + count if count == config.limit else None,
                    has_more=count == config.limit)
            if write:
                output["write_acknowledged"] = True
            await self.emit(output)
            return output
        except (ValueError, TypeError):
            return {"status": "unknown" if write else "error", "operation": config.operation,
                "error": "Splitwise returned an incomplete or invalid response; inspect the account before retrying a write.",
                "write_outcome": "unverified" if write else None}

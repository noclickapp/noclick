"""Shared payload builders for the mocked API."""

import json

BASE = "https://api.test"
USER_ID = "user_42"


def body(request):
    return json.loads(request.content) if request.content else None


def operation(op_id="op_1", kind="human.ask", status="awaiting_human", result=None, error=None, **extra):
    return {
        "object": "operation", "id": op_id, "kind": kind, "status": status,
        "result": result, "error": error,
        "created_at": "2026-09-25T10:00:00Z", "updated_at": "2026-09-25T10:00:00Z", **extra,
    }


def user_row(user_id=USER_ID, **extra):
    return {
        "object": "user", "id": user_id, "name": None,
        "email": None, "phone": None, "spend_cap_usd_per_month": None, "metadata": {},
        "status": "active", "created_at": "2026-09-25T10:00:00Z", **extra,
    }


def agent_row(**extra):
    return {
        "object": "agent", "id": "ag_1", "name": "support", "model": "openrouter/x", "harness": "sdk",
        "instructions": "hi", "tools": [], "user_id": None, "workflow_id": "wf_1", "parent_id": None,
        "ttl_s": None, "expires_at": "2026-09-26T12:00:00Z", "budget_usd_per_month": 50,
        "created_at": "2026-09-25T10:00:00Z", **extra,
    }


def trash_item(kind, resource_id, name, item_id="tr_1"):
    return {"object": "trash_item", "id": item_id, "kind": kind, "resource_id": resource_id, "name": name,
            "user_id": None, "trashed_at": "2026-09-25T10:00:00Z", "purge_after": "2026-10-25T10:00:00Z"}


def trashed(kind, resource_id, name, item_id="tr_1"):
    """What a delete answers: the resource gone to the trash, with the operation that undoes it."""
    item = trash_item(kind, resource_id, name, item_id)
    return {"object": kind, "id": resource_id, "deleted": True, "trash": item,
            "restorable_until": item["purge_after"], "operation_id": "op_del"}


def listing(*rows, next_cursor=None):
    return {"object": "list", "data": list(rows), "next_cursor": next_cursor}


def integration_row(name="gmail", **extra):
    """A ``GET /v1/integrations`` row."""
    return {
        "object": "integration", "name": name, "label": name.capitalize(), "kind": "app", "subscription": False,
        "connect_with": ["oauth"],
        "credential_types": [f"{name.capitalize()}OAuth"], "operation_count": 1, "account_free_operation_count": 0,
        **extra,
    }


def operation_row(name="send_email", **extra):
    """One operation of an integration's catalog."""
    return {
        "name": name, "description": "Send an email", "parameters": {"type": "object", "properties": {}, "required": []},
        "read_only": False, "scopes": [], "needs_account": True, **extra,
    }

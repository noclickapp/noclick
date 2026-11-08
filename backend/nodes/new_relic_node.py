"""New Relic workflow operations using a user API key.

NerdGraph is the primary New Relic API. The small REST v2 surface here covers
APM applications and deployments, which are still documented there. Both APIs
accept the same user key; data-ingest license keys are not accepted.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

_HOSTS = {
    "us": "https://api.newrelic.com",
    "eu": "https://api.eu.newrelic.com",
    "jp": "https://api.jp.newrelic.com",
}


class NewRelicUserKeyCredential(BaseModel):
    credential_type: Literal["new_relic_user_key"] = Field(
        "new_relic_user_key", json_schema_extra={"ui:hidden": True},
    )
    api_key: str = Field(
        ..., min_length=1, title="User API Key",
        description="Create a User key in New Relic's API keys page. License and browser keys cannot query NerdGraph.",
        json_schema_extra={"ui:widget": "password"},
    )
    region: Literal["us", "eu", "jp"] = Field("us", title="Data Center Region")

    model_config = ConfigDict(title="New Relic User Key", json_schema_extra={
        "x-credential-url": "https://one.newrelic.com/api-keys",
        "x-help-text": "Use a New Relic User key from the US, EU, or JP data center that hosts your account.",
    })


@dataclass(frozen=True)
class Operation:
    title: str
    category: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    destructive: bool = False


OPERATIONS: dict[str, Operation] = {
    "get_current_user": Operation("Get Current User", "Accounts"),
    "list_accounts": Operation("List Accounts", "Accounts"),
    "get_account": Operation("Get Account", "Accounts", ("account_id",)),
    "run_nrql": Operation("Run NRQL Query", "Queries", ("account_id", "nrql")),
    "search_entities": Operation("Search Entities", "Entities", ("search_query",), ("cursor",)),
    "get_entity": Operation("Get Entity", "Entities", ("entity_guid",)),
    "list_dashboards": Operation("List Dashboards", "Dashboards"),
    "get_dashboard": Operation("Get Dashboard", "Dashboards", ("entity_guid",)),
    "create_dashboard": Operation("Create Dashboard", "Dashboards", ("account_id", "dashboard_json")),
    "delete_dashboard": Operation("Delete Dashboard", "Dashboards", ("entity_guid", "confirm_delete"), destructive=True),
    "undelete_dashboard": Operation("Undelete Dashboard", "Dashboards", ("entity_guid",)),
    "list_alert_policies": Operation("List Alert Policies", "Alerts", ("account_id",), ("cursor",)),
    "create_alert_policy": Operation("Create Alert Policy", "Alerts", ("account_id", "policy_name"), ("incident_preference",)),
    "rename_alert_policy": Operation("Rename Alert Policy", "Alerts", ("account_id", "policy_id", "policy_name")),
    "delete_alert_policy": Operation("Delete Alert Policy", "Alerts", ("account_id", "policy_id", "confirm_delete"), destructive=True),
    "list_applications": Operation("List APM Applications", "APM"),
    "get_application": Operation("Get APM Application", "APM", ("application_id",)),
    "list_deployments": Operation("List APM Deployments", "APM", ("application_id",)),
    "list_application_metrics": Operation("List APM Metrics", "APM", ("application_id",)),
}


def _field(name: str) -> tuple[Any, Any]:
    title = name.replace("_", " ").title()
    if name in {"account_id", "application_id"}:
        extra = {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True}} if name == "account_id" else None
        return int, Field(..., ge=1, title=title, json_schema_extra=extra)
    if name == "confirm_delete":
        return bool, Field(..., title="Confirm deletion", description="Required for deletion operations.")
    if name == "incident_preference":
        return Literal["PER_POLICY", "PER_CONDITION", "PER_CONDITION_AND_TARGET"], Field("PER_POLICY", title="Incident Preference")
    if name == "cursor":
        return Optional[str], Field(None, title="Next Cursor")
    if name in {"dashboard_json"}:
        return str, Field(..., title="Dashboard Configuration (JSON)", json_schema_extra={"ui:widget": "textarea"})
    if name == "nrql":
        return str, Field(..., title="NRQL Query", json_schema_extra={"ui:widget": "textarea"})
    return str, Field(..., min_length=1, title=title)


def _config_model(name: str, spec: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(name, json_schema_extra={
            "const": name, "ui:hidden": True, "x-category": spec.category,
            "x-display-name": spec.title,
        }))
    }
    fields.update({field: _field(field) for field in spec.required + spec.optional})
    return create_model(
        "NewRelic" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


_CONFIGS = tuple(_config_model(name, spec) for name, spec in OPERATIONS.items())
NewRelicConfig = Annotated[Union[_CONFIGS], Discriminator("operation")]


class NewRelicNodeConfig(NodeConfig[NewRelicConfig, NewRelicUserKeyCredential]):
    pass


def _json_object(value: str, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


async def _graphql(credential: NewRelicUserKeyCredential, document: str,
                   variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    host = _HOSTS[credential.region]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{host}/graphql", json={"query": document, "variables": variables or {}},
            headers={"Api-Key": credential.api_key, "Content-Type": "application/json"},
        )
    if response.is_error:
        raise ValueError(f"New Relic NerdGraph returned HTTP {response.status_code}")
    payload = response.json()
    if payload.get("errors"):
        # GraphQL error messages can quote arguments; do not expose them or
        # accidentally echo the user key into a workflow execution.
        raise ValueError(f"New Relic NerdGraph returned {len(payload['errors'])} GraphQL error(s)")
    return payload.get("data") or {}


async def _rest(credential: NewRelicUserKeyCredential, path: str) -> dict[str, Any]:
    if not path.startswith("/v2/") or not path.endswith(".json"):
        raise ValueError("New Relic REST path must target the documented v2 JSON API")
    host = _HOSTS[credential.region]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{host}{path}", headers={"Api-Key": credential.api_key})
    if response.is_error:
        raise ValueError(f"New Relic REST API returned HTTP {response.status_code}")
    return response.json()


def _graphql_operation(action: str, values: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build a documented NerdGraph query or mutation with bound variables."""
    account_id = values.get("account_id")
    if action == "get_current_user":
        return "query { actor { user { name email } } }", {}
    if action == "list_accounts":
        return "query { actor { accounts { id name } } }", {}
    if action == "get_account":
        return "query($id: Int!) { actor { account(id: $id) { id name } } }", {"id": account_id}
    if action == "run_nrql":
        return "query($id: Int!, $nrql: Nrql!) { actor { account(id: $id) { nrql(query: $nrql) { results } } } }", {"id": account_id, "nrql": values["nrql"]}
    if action == "search_entities":
        return "query($q: String!, $cursor: String) { actor { entitySearch(query: $q) { count results(cursor: $cursor) { nextCursor entities { guid name entityType } } } } }", {"q": values["search_query"], "cursor": values.get("cursor")}
    if action == "get_entity":
        return "query($guid: EntityGuid!) { actor { entity(guid: $guid) { guid name entityType } } }", {"guid": values["entity_guid"]}
    if action == "list_dashboards":
        return "query { actor { entitySearch(queryBuilder: { type: DASHBOARD }) { results { nextCursor entities { guid name entityType } } } } }", {}
    if action == "get_dashboard":
        return "query($guid: EntityGuid!) { actor { entity(guid: $guid) { ... on DashboardEntity { guid name permissions pages { guid name widgets { id title } } } } } }", {"guid": values["entity_guid"]}
    if action == "create_dashboard":
        dashboard = _json_object(values["dashboard_json"], "Dashboard configuration")
        return "mutation($id: Int!, $dashboard: DashboardInput!) { dashboardCreate(accountId: $id, dashboard: $dashboard) { entityResult { guid name } errors { type description } } }", {"id": account_id, "dashboard": dashboard}
    if action == "delete_dashboard":
        return "mutation($guid: EntityGuid!) { dashboardDelete(guid: $guid) { status errors { type description } } }", {"guid": values["entity_guid"]}
    if action == "undelete_dashboard":
        return "mutation($guid: EntityGuid!) { dashboardUndelete(guid: $guid) { errors { type description } } }", {"guid": values["entity_guid"]}
    if action == "list_alert_policies":
        return "query($id: Int!, $cursor: String) { actor { account(id: $id) { alerts { policiesSearch(cursor: $cursor) { nextCursor totalCount policies { id name incidentPreference } } } } } }", {"id": account_id, "cursor": values.get("cursor")}
    if action == "create_alert_policy":
        name = json.dumps(values["policy_name"])
        preference = values.get("incident_preference") or "PER_POLICY"
        return f"mutation {{ alertsPolicyCreate(accountId: {account_id}, policy: {{ name: {name}, incidentPreference: {preference} }}) {{ id name incidentPreference }} }}", {}
    if action == "rename_alert_policy":
        name = json.dumps(values["policy_name"])
        policy_id = json.dumps(values["policy_id"])
        return f"mutation {{ alertsPolicyUpdate(accountId: {account_id}, id: {policy_id}, policy: {{ name: {name} }}) {{ id name incidentPreference }} }}", {}
    if action == "delete_alert_policy":
        policy_id = json.dumps(values["policy_id"])
        return f"mutation {{ alertsPolicyDelete(accountId: {account_id}, id: {policy_id}) {{ id }} }}", {}
    raise ValueError(f"Unsupported NerdGraph action: {action}")


class NewRelicNode(WorkflowNode):
    """Query New Relic data and manage dashboards and alert policies."""

    integration_type = "automation-new-relic"

    edit_examples = [
        "Run an NRQL query to monitor API error rate",
        "List New Relic APM applications and their deployments",
        "Search monitored services and dashboards",
        "Create a New Relic alert policy",
    ]
    connection_evidence = ConnectionEvidence(
        field="account_id", noun="accounts", identity_operation="get_current_user",
    )

    @classmethod
    def get_config_model(cls):
        return NewRelicNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
        page_token: Optional[str] = None, search: Optional[str] = None,
    ) -> dict[str, Any]:
        if field_name != "account_id" or not credential_data or not credential_data.get("api_key"):
            return {"options": [], "next_page_token": None}
        credential = NewRelicUserKeyCredential.model_validate(credential_data)
        result = await _graphql(credential, "query { actor { accounts { id name } } }")
        accounts = ((result.get("actor") or {}).get("accounts") or [])
        options = [{"label": str(row.get("name") or row["id"]), "value": str(row["id"])}
                   for row in accounts if isinstance(row, dict) and row.get("id")]
        if search:
            options = [item for item in options if search.casefold() in item["label"].casefold()]
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        if not isinstance(self.config, NewRelicNodeConfig):
            raise ValueError("Valid New Relic configuration is required")
        values = self.config.config.model_dump(exclude_none=True)
        action = values["operation"]
        if OPERATIONS[action].destructive and values.get("confirm_delete") is not True:
            raise ValueError("Confirm deletion before running this action")
        credential = self.config.credentials
        if not credential:
            raise ValueError("A New Relic User API key is required")

        if action in {"list_applications", "get_application", "list_deployments", "list_application_metrics"}:
            app_id = values.get("application_id")
            if action == "list_applications":
                path = "/v2/applications.json"
            elif action == "get_application":
                path = f"/v2/applications/{quote(str(app_id), safe='')}.json"
            elif action == "list_deployments":
                path = f"/v2/applications/{quote(str(app_id), safe='')}/deployments.json"
            else:
                path = f"/v2/applications/{quote(str(app_id), safe='')}/metrics.json"
            data = await _rest(credential, path)
        else:
            document, variables = _graphql_operation(action, values)
            data = await _graphql(credential, document, variables)
            for key in ("dashboardCreate", "dashboardDelete", "dashboardUndelete"):
                nested = data.get(key) or {}
                if nested.get("errors"):
                    raise ValueError(f"New Relic {key} returned {len(nested['errors'])} validation error(s)")

        return {"status": "success", "operation": action, "data": data,
                "timing_ms": {"total": round((time.monotonic() - started) * 1000, 2)}}

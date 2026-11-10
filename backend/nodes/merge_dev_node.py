"""Merge Unified API: pinned v1 OpenAPI contracts.

Outgoing webhooks require dashboard setup; /webhook-receivers configures incoming
third-party deliveries. Polling follows docs.merge.dev/merge-unified/reading-data/
webhooks/merge-webhooks and the category list endpoints' modified_after filter.
"""
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

class MergeDevCredential(BaseModel):
    model_config = ConfigDict(title="Merge.dev API Key", json_schema_extra={"x-credential-instructions": "Paste your Merge API key and the linked account token from the Merge dashboard. Use a linked account for the API category your operation uses.", "x-credential-url": "https://app.merge.dev/keys"})
    credential_type: Literal["merge_dev_api_key"] = Field("merge_dev_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})
    account_token: str = Field(..., title="Account Token", min_length=1, json_schema_extra={"ui:widget": "password"})

    api_category: Literal["hris", "ats", "ticketing", "crm"] = Field("hris", title="Linked Account API Category", description="Category of this linked account; used to verify the connection.")

class CandidateFields(BaseModel):
    first_name: str | None = Field(None, title="First Name")
    last_name: str | None = Field(None, title="Last Name")
    company: str | None = Field(None, title="Company")
    title: str | None = Field(None, title="Job Title")
    locations: list[str] | None = Field(None, title="Locations")
    tags: list[str] | None = Field(None, title="Tags")

class TicketFields(BaseModel):
    name: str | None = Field(None, title="Name")
    description: str | None = Field(None, title="Description")
    status: Literal["OPEN", "CLOSED", "IN_PROGRESS", "ON_HOLD"] | None = Field(None, title="Status")
    assignees: list[UUID] | None = Field(None, title="Assignee IDs")
    collections: list[UUID] | None = Field(None, title="Collection IDs")

OPERATIONS = {'list_employees': ('hris', 'GET', '/employees'), 'get_employees': ('hris', 'GET', '/employees/{id}'), 'list_companies': ('hris', 'GET', '/companies'), 'get_companies': ('hris', 'GET', '/companies/{id}'), 'list_candidates': ('ats', 'GET', '/candidates'), 'get_candidates': ('ats', 'GET', '/candidates/{id}'), 'list_applications': ('ats', 'GET', '/applications'), 'get_applications': ('ats', 'GET', '/applications/{id}'), 'list_jobs': ('ats', 'GET', '/jobs'), 'get_jobs': ('ats', 'GET', '/jobs/{id}'), 'list_tickets': ('ticketing', 'GET', '/tickets'), 'get_tickets': ('ticketing', 'GET', '/tickets/{id}'), 'list_comments': ('ticketing', 'GET', '/comments'), 'get_comments': ('ticketing', 'GET', '/comments/{id}'), 'list_contacts': ('crm', 'GET', '/contacts'), 'get_contacts': ('crm', 'GET', '/contacts/{id}'), 'create_candidates': ('ats', 'POST', '/candidates'), 'update_candidates': ('ats', 'PATCH', '/candidates/{id}'), 'create_tickets': ('ticketing', 'POST', '/tickets'), 'update_tickets': ('ticketing', 'PATCH', '/tickets/{id}'), 'get_account_details': ('hris', 'GET', '/account-details'), 'on_new_or_updated_employees': ('hris', 'GET', '/employees'), 'on_new_or_updated_candidates': ('ats', 'GET', '/candidates'), 'on_new_or_updated_tickets': ('ticketing', 'GET', '/tickets')}

def _config(name, spec):
    category, method, path = spec
    trigger = name.startswith("on_")
    fields = {"operation": (Literal[name], Field(name, title=name.replace("_", " ").title(), json_schema_extra={"ui:hidden": True, "x-is-trigger": trigger, "x-category": "Triggers" if trigger else category.upper()}))}
    if "{id}" in path:
        fields["id"] = (UUID, Field(..., title="Resource ID"))
    if method == "GET" and path != "/account-details" and "{id}" not in path:
        fields["modified_after"] = (datetime | None, Field(None, title="Modified After"))
        if not trigger:
            fields["cursor"] = (str | None, Field(None, title="Cursor"))
            fields["page_size"] = (int, Field(100, ge=1, le=100, title="Page Size"))
    if method in {"POST", "PATCH"}:
        fields["model"] = (CandidateFields if category == "ats" else TicketFields, Field(..., title="Fields"))
        if category == "ats":
            fields["remote_user_id"] = (str, Field(..., min_length=1, title="Remote User ID", description="The ID of the remote user performing the write."))
    return create_model("MergeDev" + name.title().replace("_", "") + "Config", __base__=PollTriggerConfigBase if trigger else BaseModel, **fields)

CONFIGS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIGS.values()})
Operation = Annotated[Union[tuple(CONFIGS.values())], Field(discriminator="operation")]

class MergeDevConfig(NodeConfig[Operation, MergeDevCredential]):
    pass

class MergeDevNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-merge-dev"
    connection_evidence = ConnectionEvidence(operation="get_account_details", noun="linked account", identity_operation="get_account_details", identity_keys=("end_user_organization_name", "integration"))

    @classmethod
    def get_config_model(cls):
        return MergeDevConfig

    async def _request(self, category, method, path, *, params=None, body=None):
        credential = self.config.credentials
        async with guarded_async_client(timeout=30) as client:
            response = await client.request(method, f"https://api.merge.dev/api/{category}/v1{path}", headers={"Authorization": "Bearer " + credential.api_key, "X-Account-Token": credential.account_token, "Accept": "application/json"}, params=params, json=body)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Merge returned an invalid object")
        return data

    @staticmethod
    def _cursor(data, category, path):
        cursor = data.get("next")
        if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 8192):
            raise ValueError("Merge returned an invalid pagination cursor")
        return cursor

    async def execute(self, inputs: dict[str, Any]):
        if not self.config.credentials:
            raise ValueError("Connect a Merge.dev API key and account token")
        config = self.config.config
        name = config.operation
        category, method, path = OPERATIONS[name]
        if name == "get_account_details":
            category = self.config.credentials.api_category
        if "{id}" in path:
            path = path.replace("{id}", quote(str(config.id), safe=""))
        params = {}
        if hasattr(config, "modified_after") and config.modified_after is not None:
            params["modified_after"] = config.modified_after.isoformat()
        trigger = name.startswith("on_")
        listing = method == "GET" and path != "/account-details" and not hasattr(config, "id")
        if listing:
            params["page_size"] = 100 if trigger else config.page_size
            if not trigger and config.cursor:
                params["cursor"] = config.cursor
        body = None
        if method in {"POST", "PATCH"}:
            body = {"model": config.model.model_dump(mode="json", exclude_unset=True)}
            if not body["model"]:
                raise ValueError("Supply at least one field to write")
            if category == "ats":
                body["remote_user_id"] = config.remote_user_id
        data = await self._request(category, method, path, params=params, body=body)
        if not listing:
            return data
        if not isinstance(data.get("results"), list):
            raise ValueError("Merge list response lacks results")
        if not trigger:
            return {**data, "next_cursor": self._cursor(data, category, path)}
        rows = list(data["results"])
        seen = set()
        for _ in range(99):
            cursor = self._cursor(data, category, path)
            if cursor is None:
                break
            if cursor in seen:
                raise ValueError("Merge repeated a pagination cursor")
            seen.add(cursor)
            data = await self._request(category, method, path, params={**params, "cursor": cursor})
            if not isinstance(data.get("results"), list):
                raise ValueError("Merge list response lacks results")
            rows.extend(data["results"])
        else:
            raise ValueError("Merge polling scope exceeds 10,000 records; set Modified After")
        for row in rows:
            if not isinstance(row, dict) or not row.get("id") or not row.get("modified_at"):
                raise ValueError("Merge poll record lacks id or modified_at")
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]) + ":" + row["modified_at"])
        return {"operation": name, "items": fresh, "count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("count")) if config.get("operation", "").startswith("on_") else True

    @classmethod
    def resolve_agent_event(cls, output):
        if "items" not in output:
            return super().resolve_agent_event(output)
        if not output["items"]:
            return None
        lines = [f"- {row.get('display_full_name') or row.get('name') or ' '.join(filter(None, [row.get('first_name'), row.get('last_name')])) or row['id']} (id {row['id']}): {row.get('description') or ''}" for row in output["items"][:10]]
        return {"text": "Merge.dev: new or updated records (" + str(output.get("operation")) + ")\n" + "\n".join(lines), "conversation_key": None}

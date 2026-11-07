"""ActiveCampaign v3 contacts, CRM, marketing, and reporting operations.

The account-specific API URL and per-user API key come from Settings > Developer.
ActiveCampaign's public v3 API authenticates with ``Api-Token``, not OAuth.
Endpoint paths and request envelopes are pinned to the published OpenAPI pages at
https://developers.activecampaign.com/reference/overview.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client, normalize_https_origin


def _base_url(api_url: str) -> str:
    """Accept precisely the account URL shown by ActiveCampaign's Developer tab."""
    parts = urlsplit(api_url.strip())
    if parts.path.rstrip("/") != "/api/3" or parts.query or parts.fragment:
        raise ValueError("ActiveCampaign API URL must end in /api/3")
    origin = normalize_https_origin(
        f"{parts.scheme}://{parts.netloc}", field_name="ActiveCampaign API URL"
    )
    return origin + "/api/3"


class ActiveCampaignApiKeyCredential(BaseModel):
    credential_type: Literal["activecampaign_api_key"] = Field(
        "activecampaign_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_url: str = Field(
        ..., title="API URL",
        description="The complete account-specific API URL from Settings > Developer, ending in /api/3",
    )
    api_key: str = Field(
        ..., title="API Key", json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(title="ActiveCampaign API Key", json_schema_extra={
        "x-credential-url": "https://help.activecampaign.com/hc/en-us/articles/207317590-Getting-started-with-the-API",
    })


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    body_root: str | None = None
    body_required: bool = False
    required_query: tuple[str, ...] = ()


# Paths and envelopes are from the official OpenAPI definitions. Most body fields
# are intentionally JSON: ActiveCampaign has account/plan-specific custom fields
# and nested resource shapes which a fixed form would silently drop.
OPERATIONS: dict[str, Operation] = {
    "list_contacts": Operation("List Contacts", "Contacts", "GET", "/contacts"),
    "get_contact": Operation("Get Contact", "Contacts", "GET", "/contacts/{id}"),
    "create_contact": Operation("Create Contact", "Contacts", "POST", "/contacts", "contact", True),
    "update_contact": Operation("Update Contact", "Contacts", "PUT", "/contacts/{id}", "contact", True),
    "sync_contact": Operation("Upsert Contact", "Contacts", "POST", "/contact/sync", "contact", True),
    "bulk_sync_contacts": Operation("Bulk Upsert Contacts", "Contacts", "POST", "/contact/bulkSync", None, True),
    "bulk_import_contacts": Operation("Bulk Import Contacts", "Contacts", "POST", "/import/bulk_import", None, True),
    "list_imports": Operation("List Bulk Imports", "Contacts", "GET", "/import/bulk_import"),
    "get_import_status": Operation("Get Bulk Import Status", "Contacts", "GET", "/import/info"),
    "list_contact_activities": Operation("List Contact Activities", "Contacts", "GET", "/activities"),
    "list_contact_notes": Operation("List Contact Notes", "Contacts", "GET", "/contacts/{id}/notes"),
    "list_contact_lists": Operation("List Contact List Memberships", "Contacts", "GET", "/contacts/{id}/contactLists"),
    "list_contact_deals": Operation("List Contact Deals", "Contacts", "GET", "/contacts/{id}/deals"),
    "list_contact_account_links": Operation("List Contact Account Links", "Contacts", "GET", "/contacts/{id}/accountContacts"),
    "list_contact_field_values": Operation("List Contact Field Values", "Contacts", "GET", "/contacts/{id}/fieldValues"),
    "create_contact_note": Operation("Create Contact Note", "Contacts", "POST", "/contacts/{id}/notes", "note", True),
    "update_contact_note": Operation("Update Contact Note", "Contacts", "PUT", "/contacts/{id}/notes/{noteId}", "note", True),
    "delete_contact_note": Operation("Delete Contact Note", "Contacts", "DELETE", "/contacts/{id}/notes/{noteId}"),
    "add_contact_tags": Operation("Add Tags to Contact", "Tags", "POST", "/contacts/{contactId}/tags", None, True),
    "remove_contact_tag_by_name": Operation("Remove Contact Tag by Name", "Tags", "DELETE", "/contacts/{contactId}/tags", required_query=("tag",)),
    "remove_contact_tag_by_id": Operation("Remove Contact Tag by ID", "Tags", "DELETE", "/contacts/{contactId}/tags/{tagId}"),
    "list_tags": Operation("List Tags", "Tags", "GET", "/tags"),
    "list_lists": Operation("List Lists", "Lists", "GET", "/lists"),
    "create_list": Operation("Create List", "Lists", "POST", "/lists", "list", True),
    "update_list": Operation("Update List", "Lists", "PUT", "/lists/{id}", "list", True),
    "list_contact_automations": Operation("List Contact Automations", "Automations", "GET", "/contactAutomations"),
    "list_automations": Operation("List Automations", "Automations", "GET", "/automations"),
    "list_automation_contacts": Operation("List Contacts in Automation", "Automations", "GET", "/automations/{seriesId}/contactAutomations"),
    "add_contact_to_automation": Operation("Add Contact to Automation", "Automations", "POST", "/contactAutomations", "contactAutomation", True),
    "remove_contact_from_automation": Operation("Remove Contact from Automation", "Automations", "DELETE", "/contactAutomations", required_query=("contact", "automation")),
    "list_deals": Operation("List Deals", "Deals", "GET", "/deals"),
    "get_deal": Operation("Get Deal", "Deals", "GET", "/deals/{id}"),
    "create_deal": Operation("Create Deal", "Deals", "POST", "/deals", "deal", True),
    "update_deal": Operation("Update Deal", "Deals", "PUT", "/deals/{id}", "deal", True),
    "list_pipelines": Operation("List Deal Pipelines", "Deals", "GET", "/dealGroups"),
    "list_deal_stages": Operation("List Deal Stages", "Deals", "GET", "/dealStages"),
    "get_deal_stage": Operation("Get Deal Stage", "Deals", "GET", "/dealStages/{id}"),
    "update_deal_note": Operation("Update Deal Note", "Deals", "PUT", "/deals/{id}/notes/{noteId}", "note", True),
    "list_deal_tasks": Operation("List Deal Tasks", "Deals", "GET", "/dealTasks"),
    "create_task_reminder": Operation("Create Task Reminder", "Deals", "POST", "/taskNotifications", None, True),
    "list_deal_fields": Operation("List Deal Custom Fields", "Deals", "GET", "/dealCustomFieldMeta"),
    "get_deal_field": Operation("Get Deal Custom Field", "Deals", "GET", "/dealCustomFieldMeta/{id}"),
    "create_deal_field": Operation("Create Deal Custom Field", "Deals", "POST", "/dealCustomFieldMeta", "dealCustomFieldMetum", True),
    "list_contact_fields": Operation("List Contact Custom Fields", "Custom Fields", "GET", "/fields"),
    "get_contact_field": Operation("Get Contact Custom Field", "Custom Fields", "GET", "/fields/{id}"),
    "create_contact_field": Operation("Create Contact Custom Field", "Custom Fields", "POST", "/fields", "field", True),
    "create_field_value": Operation("Set Contact Field Value", "Custom Fields", "POST", "/fieldValues", "fieldValue", True),
    "update_field_value": Operation("Update Contact Field Value", "Custom Fields", "PUT", "/fieldValues/{id}", "fieldValue", True),
    "list_contact_field_groups": Operation("List Contact Field Groups", "Custom Fields", "GET", "/groupMembers"),
    "list_segments": Operation("List Segments", "Segments", "GET", "/segments"),
    "get_segment": Operation("Get Segment", "Segments", "GET", "/segments/{id}"),
    "create_segment": Operation("Create Segment", "Segments", "POST", "/segmentsV2", None, True),
    "update_segment": Operation("Update Segment", "Segments", "PUT", "/segmentsV2/{segmentId}", None, True),
    "delete_segment": Operation("Delete Segment", "Segments", "DELETE", "/segmentsV2/{segmentId}"),
    "list_campaigns": Operation("List Campaigns", "Campaigns", "GET", "/campaigns"),
    "create_campaign": Operation("Create Campaign", "Campaigns", "POST", "/campaigns", "campaign", True),
    "create_empty_campaign": Operation("Create Empty Campaign", "Campaigns", "POST", "/campaign", None, True),
    "edit_campaign": Operation("Edit Campaign", "Campaigns", "PUT", "/campaigns/{id}/edit", None, True),
    "duplicate_campaign": Operation("Duplicate Campaign", "Campaigns", "POST", "/campaigns/{id}/copy"),
    "schedule_campaign": Operation("Schedule Campaign", "Campaigns", "PUT", "/campaigns/{campaignId}/enable"),
    "pause_campaign": Operation("Pause Campaign", "Campaigns", "PUT", "/campaigns/{campaignId}/pause"),
    "resume_campaign": Operation("Resume Campaign", "Campaigns", "PUT", "/campaigns/{campaignId}/resume"),
    "stop_campaign": Operation("Stop Campaign", "Campaigns", "PUT", "/campaigns/{campaignId}/stop"),
    "list_campaign_messages": Operation("List Campaign Messages", "Campaigns", "GET", "/campaign/{campaignId}/messages"),
    "get_campaign_message": Operation("Get Campaign Message", "Campaigns", "GET", "/campaign/{campaignId}/messages/{id}"),
    "list_campaign_opens": Operation("List Campaign Opens", "Campaign Reports", "GET", "/campaigns/{campaignId}/reports/opens"),
    "list_campaign_clicks": Operation("List Campaign Clicks", "Campaign Reports", "GET", "/campaigns/{campaignId}/reports/clicks"),
    "list_campaign_bounces": Operation("List Campaign Bounces", "Campaign Reports", "GET", "/campaigns/{campaignId}/reports/bounces"),
    "list_campaign_unsubscribes": Operation("List Campaign Unsubscribes", "Campaign Reports", "GET", "/campaigns/{campaignId}/reports/unsubscribes"),
    "list_forms": Operation("List Forms", "Forms", "GET", "/forms"),
    "create_form": Operation("Create Form", "Forms", "POST", "/forms", None, True),
    "update_form": Operation("Update Form", "Forms", "PUT", "/forms/{id}", None, True),
    "delete_form": Operation("Delete Form", "Forms", "DELETE", "/forms/{id}"),
    "list_templates": Operation("List Email Templates", "Templates", "GET", "/templates"),
    "create_template": Operation("Create Email Template", "Templates", "POST", "/templates", "template", True),
    "update_template": Operation("Update Email Template", "Templates", "PUT", "/templates/{id}", "template", True),
    "get_account_info": Operation("Get Account Information", "Account", "GET", "/settings/account"),
}


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    extra = {"const": name, "ui:hidden": True, "x-category": op.category,
             "x-is-trigger": False, "x-display-name": op.label}
    if name.startswith("create_") or name == "sync_contact":
        extra.update({"x-creates-resource": True, "x-resource-type": "activecampaign_" + name.removeprefix("create_")})
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(name, title=op.label, json_schema_extra=extra))
    }
    for key in re.findall(r"\{([^}]+)\}", op.path):
        title = " ".join(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", key)).title()
        fields[key] = (str, Field(..., title=title or "ID"))
    for key in op.required_query:
        fields[key] = (str, Field(..., title=key.title(),
            description=f"Required {key} query parameter"))
    if op.body_required:
        root_description = (f"The {op.body_root} object, without its outer wrapper"
                            if op.body_root else "The complete JSON request body")
        fields["payload_json"] = (str, Field(..., title="Request JSON",
            description=root_description,
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    if op.method in ("GET", "DELETE"):
        fields["query_json"] = (Optional[str], Field(None, title="Query Parameters JSON",
            description='Optional filters and pagination, for example {"limit": 20, "offset": 0}',
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}))
    return create_model("ActiveCampaign" + "".join(part.title() for part in name.split("_")) + "Config",
                        __module__=__name__, **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class ActiveCampaignOnNewContactConfig(PollTriggerConfigBase):
    operation: Literal["on_new_contact"] = Field(
        "on_new_contact", title="On New Contact",
        json_schema_extra={"const": "on_new_contact", "ui:hidden": True,
                           "x-category": "Triggers", "x-is-trigger": True,
                           "x-display-name": "On New Contact"},
    )
    list_id: Optional[str] = Field(None, title="List ID",
        description="Optional list to monitor; leave blank for all contacts")


ActiveCampaignConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values()) + (ActiveCampaignOnNewContactConfig,)],
    Discriminator("operation"),
]


class ActiveCampaignNodeConfig(NodeConfig[ActiveCampaignConfig, ActiveCampaignApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


class ActiveCampaignNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-activecampaign"
    connection_evidence = ConnectionEvidence(operation="list_contacts", noun="contacts")
    edit_examples = [
        "Create a contact in ActiveCampaign", "Add a tag to an ActiveCampaign contact",
        "Move a deal through the CRM", "List contacts who opened a campaign",
    ]

    @classmethod
    def get_config_model(cls):
        return ActiveCampaignNodeConfig

    @classmethod
    def should_propagate_output(cls, output: dict[str, Any], config: dict[str, Any]) -> bool:
        if config.get("operation") == "on_new_contact":
            return bool(output.get("new_contact_count"))
        return True

    @staticmethod
    async def _request(credential: ActiveCampaignApiKeyCredential, method: str,
                       path: str, *, params=None, body=None) -> dict[str, Any]:
        url = _base_url(credential.api_url) + path
        async with guarded_async_client(timeout=45.0) as client:
            response = await client.request(
                method, url, params=params, json=body,
                headers={"Api-Token": credential.api_key, "Accept": "application/json"},
            )
        try:
            data = response.json() if response.content else {"ok": True}
        except ValueError as exc:
            raise ValueError(f"ActiveCampaign returned a non-JSON response ({response.status_code})") from exc
        if response.is_error:
            detail = data.get("message") or data.get("errors") or data.get("error") or "request failed" if isinstance(data, dict) else "request failed"
            raise ValueError(f"ActiveCampaign API error {response.status_code}: {detail}")
        return data

    async def _poll_contacts(self, credential: ActiveCampaignApiKeyCredential,
                             list_id: Optional[str]) -> dict[str, Any]:
        contacts: list[dict[str, Any]] = []
        last_id: str | None = None
        for _ in range(10):
            params: dict[str, Any] = {"limit": 100, "orders[id]": "desc"}
            if list_id:
                params["listid"] = list_id
            if last_id:
                params["id_less"] = last_id
            data = await self._request(credential, "GET", "/contacts", params=params)
            rows = data.get("contacts", [])
            if not isinstance(rows, list):
                raise ValueError("ActiveCampaign contacts response was not a list")
            contacts.extend(row for row in rows if isinstance(row, dict))
            if len(rows) < 100:
                break
            last_id = str(rows[-1].get("id") or "")
            if not last_id:
                raise ValueError("ActiveCampaign contact page is missing an ID")
        else:
            raise ValueError("More than 1,000 contacts match this trigger; narrow it to a list")
        fresh = await self._filter_unseen(contacts, lambda row: str(row["id"]) if row.get("id") else None)
        return {"contacts": fresh, "new_contact_count": len(fresh)}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ActiveCampaignNodeConfig):
            raise ValueError("ActiveCampaign configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an ActiveCampaign API key")
        config = self.config.config
        if isinstance(config, ActiveCampaignOnNewContactConfig):
            return await self._poll_contacts(credential, config.list_id)
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for key in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = _parse_json(values.pop("query_json"), "Query Parameters JSON") if "query_json" in values else None
        if op.required_query:
            params = {**(params or {}), **{key: values.pop(key) for key in op.required_query}}
        body = _parse_json(values.pop("payload_json"), "Request JSON") if "payload_json" in values else None
        if body is not None and op.body_root:
            body = {op.body_root: body}
        data = await self._request(credential, op.method, path, params=params, body=body)
        return {"status": "success", "operation": config.operation, "data": data}

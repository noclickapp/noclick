"""Emelia multichannel campaigns, prospect lists and enrichment.

Wire contract: https://docs.emelia.io/openapi/emelia.json (2026-10-11).
Each operation makes one request; pagination is explicit and writes are not retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

ObjectId = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{24}$")]
Text = Annotated[str, Field(min_length=1, max_length=10000)]
Email = Annotated[str, Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", json_schema_extra={"format": "email"})]
ContactFields = Annotated[dict[str, Union[StrictStr, StrictInt, StrictFloat, StrictBool, None]], Field(min_length=1)]


class EmeliaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Emelia API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://v3.emelia.io/settings/api",
        "x-credential-instructions": "Create an API key in Emelia Settings → API, then paste the key here. NoClick sends it in the Authorization header to api.emelia.io. Listing your campaigns checks access; it does not verify every write permission.",
    })
    credential_type: Literal["emelia_api_key"] = Field("emelia_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without an Authorization or Bearer prefix")
        return value


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CampaignOperation(Operation):
    campaign_id: ObjectId = Field(..., title="Campaign ID")


class ListOperation(Operation):
    list_id: ObjectId = Field(..., title="List ID")


class JobOperation(Operation):
    job_id: ObjectId = Field(..., title="Job ID")


class ListCampaigns(Operation):
    operation: Literal["list_campaigns"] = Field("list_campaigns", title="List Campaigns")


class GetCampaign(CampaignOperation):
    operation: Literal["get_campaign"] = Field("get_campaign", title="Get Campaign")


class CreateCampaign(Operation):
    operation: Literal["create_campaign"] = Field("create_campaign", title="Create Campaign")
    name: Text
    time_zone: str | None = Field(None, title="Time zone", description="IANA time zone, for example Europe/Paris")


class RenameCampaign(CampaignOperation):
    operation: Literal["rename_campaign"] = Field("rename_campaign", title="Rename Campaign")
    name: Text


class StartCampaign(CampaignOperation):
    operation: Literal["start_campaign"] = Field("start_campaign", title="Start Campaign")


class PauseCampaign(CampaignOperation):
    operation: Literal["pause_campaign"] = Field("pause_campaign", title="Pause Campaign")


class GetCampaignProgress(CampaignOperation):
    operation: Literal["get_campaign_progress"] = Field("get_campaign_progress", title="Get Campaign Progress")


class AddCampaignContact(CampaignOperation):
    operation: Literal["add_campaign_contact"] = Field("add_campaign_contact", title="Add Campaign Contact")
    contact: dict[str, StrictStr] = Field(..., min_length=1, description="String fields including email or linkedinUrlProfile; other keys become custom variables")

    @model_validator(mode="after")
    def identity(self):
        if not self.contact.get("email") and not self.contact.get("linkedinUrlProfile"):
            raise ValueError("A campaign contact needs email or linkedinUrlProfile")
        return self


class RemoveCampaignContact(CampaignOperation):
    operation: Literal["remove_campaign_contact"] = Field("remove_campaign_contact", title="Remove Campaign Contact")
    contact_id: ObjectId


class ListCampaignActivities(CampaignOperation):
    operation: Literal["list_campaign_activities"] = Field("list_campaign_activities", title="List Campaign Activities")
    page: Annotated[str, Field(pattern=r"^[0-9]+$")] = "0"
    search: str | None = Field(None, max_length=200)
    contact_id: ObjectId | None = None


class GetCampaignStats(CampaignOperation):
    operation: Literal["get_campaign_stats"] = Field("get_campaign_stats", title="Get Campaign Stats")


class ListLists(Operation):
    operation: Literal["list_lists"] = Field("list_lists", title="List Lists")
    page: int = Field(1, ge=1)
    limit: int = Field(25, ge=1, le=100)
    search: str | None = None


class CreateList(Operation):
    operation: Literal["create_list"] = Field("create_list", title="Create List")
    name: Text


class GetList(ListOperation):
    operation: Literal["get_list"] = Field("get_list", title="Get List")


class RenameList(ListOperation):
    operation: Literal["rename_list"] = Field("rename_list", title="Rename List")
    name: Text


class DeleteList(ListOperation):
    operation: Literal["delete_list"] = Field("delete_list", title="Delete List")


class ListListContacts(ListOperation):
    operation: Literal["list_list_contacts"] = Field("list_list_contacts", title="List List Contacts")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=100)
    search: str | None = Field(None, max_length=200)


class AddListContact(ListOperation):
    operation: Literal["add_list_contact"] = Field("add_list_contact", title="Add List Contact")
    contact: ContactFields = Field(..., description="Flat scalar contact fields, for example email, firstName, companyName and custom variables")
    update_if_exists: Literal["true", "false"] = "false"


class AddListContactsBatch(ListOperation):
    operation: Literal["add_list_contacts_batch"] = Field("add_list_contacts_batch", title="Add List Contacts Batch")
    contacts: list[ContactFields] = Field(..., min_length=1, max_length=100)
    update_if_exists: Literal["true", "false"] = "false"


class UpdateContact(Operation):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact")
    contact_id: ObjectId
    contact: ContactFields = Field(..., description="Flat scalar fields to update; null and empty strings are ignored by Emelia")


class FindEmail(Operation):
    operation: Literal["find_email"] = Field("find_email", title="Find Email")
    full_name: Text
    company_name: Text
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")] = Field(..., description="ISO 3166-1 alpha-2 country code")
    company_website: str | None = None


class GetFindEmailJob(JobOperation):
    operation: Literal["get_find_email_job"] = Field("get_find_email_job", title="Get Find Email Job")


class VerifyEmail(Operation):
    operation: Literal["verify_email"] = Field("verify_email", title="Verify Email")
    email: Email


class GetVerifyEmailJob(JobOperation):
    operation: Literal["get_verify_email_job"] = Field("get_verify_email_job", title="Get Verify Email Job")


class ListEmailProviders(Operation):
    operation: Literal["list_email_providers"] = Field("list_email_providers", title="List Email Providers")


EmeliaConfig = Annotated[Union[
    ListCampaigns,
    GetCampaign,
    CreateCampaign,
    RenameCampaign,
    StartCampaign,
    PauseCampaign,
    GetCampaignProgress,
    AddCampaignContact,
    RemoveCampaignContact,
    ListCampaignActivities,
    GetCampaignStats,
    ListLists,
    CreateList,
    GetList,
    RenameList,
    DeleteList,
    ListListContacts,
    AddListContact,
    AddListContactsBatch,
    UpdateContact,
    FindEmail,
    GetFindEmailJob,
    VerifyEmail,
    GetVerifyEmailJob,
    ListEmailProviders
], Field(discriminator="operation")]


class EmeliaNodeConfig(NodeConfig[EmeliaConfig, EmeliaAPIKeyCredential]):
    pass


# method, provider path, path fields, query fields, body fields, response field
ROUTES = {
    "list_campaigns": ('GET', '/advanced/campaigns', {}, {}, {}, 'campaigns'),
    "get_campaign": ('GET', '/advanced/campaigns/{campaignId}', {'campaign_id': 'campaignId'}, {}, {}, 'campaign'),
    "create_campaign": ('POST', '/advanced/campaigns', {}, {}, {'name': 'name', 'time_zone': 'timeZone'}, 'campaignId'),
    "rename_campaign": ('PATCH', '/advanced/campaigns/{campaignId}/name', {'campaign_id': 'campaignId'}, {}, {'name': 'name'}, 'campaign'),
    "start_campaign": ('POST', '/advanced/campaigns/{campaignId}/start', {'campaign_id': 'campaignId'}, {}, {}, 'success'),
    "pause_campaign": ('POST', '/advanced/campaigns/{campaignId}/pause', {'campaign_id': 'campaignId'}, {}, {}, 'success'),
    "get_campaign_progress": ('GET', '/advanced/campaigns/{campaignId}/progress', {'campaign_id': 'campaignId'}, {}, {}, 'progress'),
    "add_campaign_contact": ('POST', '/advanced/campaign/contacts', {}, {}, {'campaign_id': 'id', 'contact': 'contact'}, 'contactId'),
    "remove_campaign_contact": ('DELETE', '/advanced/campaign/contacts', {}, {}, {'campaign_id': 'id', 'contact_id': 'contactId'}, 'success'),
    "list_campaign_activities": ('GET', '/advanced/campaigns/{campaignId}/activities', {'campaign_id': 'campaignId'}, {'page': 'page', 'search': 'search', 'contact_id': 'contactId'}, {}, 'activities'),
    "get_campaign_stats": ('GET', '/stats/advanced', {}, {'campaign_id': 'campaignId'}, {}, 'global'),
    "list_lists": ('GET', '/lists/list', {}, {'page': 'page', 'limit': 'limit', 'search': 'search'}, {}, 'items'),
    "create_list": ('POST', '/lists/list', {}, {}, {'name': 'name'}, 'listId'),
    "get_list": ('GET', '/lists/list/{listId}', {'list_id': 'listId'}, {}, {}, '_id'),
    "rename_list": ('PATCH', '/lists/list/{listId}', {'list_id': 'listId'}, {}, {'name': 'name'}, '_id'),
    "delete_list": ('DELETE', '/lists/list/{listId}', {'list_id': 'listId'}, {}, {}, 'success'),
    "list_list_contacts": ('GET', '/lists/list/{listId}/rows', {'list_id': 'listId'}, {'page': 'page', 'page_size': 'pageSize', 'search': 'search'}, {}, 'items'),
    "add_list_contact": ('POST', '/lists/list/{listId}/contacts', {'list_id': 'listId'}, {'update_if_exists': 'updateIfExists'}, {'contact': '$root'}, 'leadId'),
    "add_list_contacts_batch": ('POST', '/lists/list/{listId}/contacts/batch', {'list_id': 'listId'}, {'update_if_exists': 'updateIfExists'}, {'contacts': 'contacts'}, 'results'),
    "update_contact": ('PATCH', '/lists/contacts/{contactId}', {'contact_id': 'contactId'}, {}, {'contact': '$root'}, 'leadId'),
    "find_email": ('POST', '/tools/find/email', {}, {}, {'full_name': 'fullname', 'company_name': 'companyName', 'country': 'country', 'company_website': 'companyWebsite'}, 'jobId'),
    "get_find_email_job": ('GET', '/tools/find/email/{jobId}', {'job_id': 'jobId'}, {}, {}, 'data'),
    "verify_email": ('POST', '/tools/verify/email', {}, {}, {'email': 'email'}, 'jobId'),
    "get_verify_email_job": ('GET', '/tools/verify/email/{jobId}', {'job_id': 'jobId'}, {}, {}, 'data'),
    "list_email_providers": ('GET', '/email-providers', {}, {}, {}, 'providers'),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class EmeliaNode(WorkflowNode):
    integration_type = "automation-emelia"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns", label_keys=("name", "_id"))
    edit_examples = ["Add a prospect to an Emelia list", "Pause this campaign", "Find and verify a prospect's email"]

    @classmethod
    def get_config_model(cls):
        return EmeliaNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Emelia API key")
        config = self.config.config
        token = self.config.credentials.api_key
        method, path, path_fields, query_fields, body_fields, response_field = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        # IDs are validated ObjectIds: no caller can change the host or route.
        path = path.format(**{target: values[source] for source, target in path_fields.items()})
        query = {target: values[source] for source, target in query_fields.items() if source in values}
        body = {target: values[source] for source, target in body_fields.items() if source in values}
        if "$root" in body:
            body = body["$root"]
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.emelia.io" + path,
                    headers={"Authorization": token, "Accept": "application/json"},
                    params=query or None, **({"json": body} if body_fields else {}))
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if not 200 <= response.status_code < 300:
                output = {"status": "error", "success": False, "http_status": response.status_code,
                          "message": payload if payload is not None else "Emelia returned a non-JSON error"}
            elif not isinstance(payload, dict) or payload.get("success") is False or payload.get("error") or payload.get("errors"):
                output = {"status": "error", "success": False, "message": payload or "Emelia returned an invalid response"}
            elif response_field not in payload:
                output = {"status": "error", "success": False, "message": "Emelia response is missing the documented result"}
            else:
                output = {"status": "success", "success": True, "data": payload, "http_status": response.status_code}
                result = payload[response_field]
                if isinstance(result, list):
                    output["items"] = result
                # Preserve provider counters and explicit page inputs. No implicit
                # traversal, assumed snapshot consistency or invented cursors.
                if "page" in values:
                    output["page"] = values["page"]
                if method != "GET":
                    output["write_acknowledged"] = True
                    output["readback_verified"] = False
        except httpx.RequestError:
            output = {"status": "error" if method == "GET" else "unknown", "success": False,
                      "message": "Emelia request did not complete; inspect the provider before retrying a write"}
        output = _redact(output, token)
        await self.emit(output)
        return output

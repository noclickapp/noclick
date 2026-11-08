"""Manyreach API v2 operations. Contract: https://api.manyreach.com/swagger/docs/v2."""
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

class ManyreachApiKey(BaseModel):
    model_config = ConfigDict(title="Manyreach API Key", json_schema_extra={"x-credential-url": "https://api.manyreach.com/swagger/ui/index", "x-credential-instructions": "Copy your API key from Manyreach account settings and paste it here. Requests send it in the X-API-Key header."})
    credential_type: Literal["manyreach_api_key"] = "manyreach_api_key"
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        return clean_secret(value)

class OperationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GetAccount(OperationBase):
    operation: Literal["get_account"] = Field("get_account", title='Get Account')

class GetCredits(OperationBase):
    operation: Literal["get_credits"] = Field("get_credits", title='Get Credits')

class ListCampaigns(OperationBase):
    operation: Literal["list_campaigns"] = Field("list_campaigns", title='List Campaigns')
    includeArchived: bool | None = Field(None, title='Includearchived', description='When false (default), rows with CampStatus archived are excluded unless Status is set to archived.')
    status: str | None = Field(None, title='Status', description='Optional exact CampStatus filter (case-insensitive), e.g. running, paused, draft, completed, archived, scheduled, preparing.')
    page: int | None = Field(None, title='Page', ge=1, le=2147483647, description='Page number (1-indexed, default: 1)')
    limit: int | None = Field(None, title='Limit', ge=1, le=1000, description='Items per page (default: 100, max: 1000)')
    startingAfter: int | None = Field(None, title='Startingafter', description='Cursor for next page (optional, for cursor-based pagination)')

class CreateCampaign(OperationBase):
    operation: Literal["create_campaign"] = Field("create_campaign", title='Create Campaign')
    name: str = Field(..., title='Name', min_length=0, max_length=256, description='Campaign display name for identification and organization; maximum 256 characters.')
    description: str | None = Field(None, title='Description', min_length=0, max_length=512, description='Optional description explaining the purpose or goal of this campaign; maximum 512 characters.')
    subject: str | None = Field(None, title='Subject', min_length=0, max_length=4000, description='Email subject line for the initial campaign email; maximum 4,000 characters.')
    body: str | None = Field(None, title='Body', description="HTML body for the initial campaign email. Include {{SENDER_SIGNATURE}} where the sender's signature should appear; it is not appended automatically. Per-campaign sign-off HTML can be written inline.")
    fromEmails: str | None = Field(None, title='Fromemails', description='Comma-separated list of sender email addresses to use for sending campaign emails.')
    dailyLimit: int | None = Field(None, title='Dailylimit', ge=1, le=10000, description='Maximum number of emails this campaign can send per day; must be between 1 and 10,000.')

class GetCampaign(OperationBase):
    operation: Literal["get_campaign"] = Field("get_campaign", title='Get Campaign')
    id: int = Field(..., title='Id', ge=1, le=2147483647)

class PauseCampaign(OperationBase):
    operation: Literal["pause_campaign"] = Field("pause_campaign", title='Pause Campaign')
    id: int = Field(..., title='Id', ge=1, le=2147483647)

class StartCampaign(OperationBase):
    operation: Literal["start_campaign"] = Field("start_campaign", title='Start Campaign')
    id: int = Field(..., title='Id', ge=1, le=2147483647)

class GetCampaignStats(OperationBase):
    operation: Literal["get_campaign_stats"] = Field("get_campaign_stats", title='Get Campaign Stats')
    id: int = Field(..., title='Id', ge=1, le=2147483647)
    dateStart: str | None = Field(None, title='Datestart', description='Optional. The start date (inclusive) for the statistics data range.\r\nAccepts ISO 8601 format: yyyy-MM-dd or yyyy-MM-ddTHH:mm:ss.fffZ (Z is optional, always interpreted as UTC).\r\nIf not provided, defaults to the campaign creation date.')
    dateEnd: str | None = Field(None, title='Dateend', description='Optional. The end date (inclusive) for the statistics data range.\r\nAccepts ISO 8601 format: yyyy-MM-dd or yyyy-MM-ddTHH:mm:ss.fffZ (Z is optional, always interpreted as UTC).\r\nIf not provided, defaults to the current date.')
    refresh: bool | None = Field(None, title='Refresh', description='Optional. Set to true to force refresh campaign statistics before retrieval.\r\nWhen true, recalculates all stats, processes A/B test variants, refreshes followups, and clears caches.\r\nDefaults to false for faster response times.')

class ListCampaignProspects(OperationBase):
    operation: Literal["list_campaign_prospects"] = Field("list_campaign_prospects", title='List Campaign Prospects')
    id: int = Field(..., title='Id', ge=1, le=2147483647)
    sendingStatus: Literal['Unknown', 'EspMatchNotFound', 'EspNotAllowed', 'NoWarmup', 'NotReceiving', 'WarmupLimits', 'SendingLimits', 'NoSender', 'Stuck', 'MailboxInexistent', 'EmptySubject', 'EmptyBody', 'MissingPlaceholder', 'Invalid', 'Blacklisted', 'Stopped', 'Unsub', 'BounceHard', 'BounceSoft', 'AutoNolonger', 'AutoOoo', 'AutoReply', 'CollegueReplied', 'SenderDisconnected', 'Paused', 'InsufficientCredit', 'ScheduleInactive', 'NotInterested', 'NotSet', 'Neutral', 'MaybeLater', 'Interested', 'MeetingBooked', 'MeetingCompleted', 'Won', 'Subbed'] | None = Field(None, title='Sendingstatus', description='Only enrollments with this campaign-level sending status (for example MissingPlaceholder).')
    sendingActive: bool | None = Field(None, title='Sendingactive', description='Only enrollments that are (true) or are not (false) still eligible to receive emails from this campaign.')
    page: int | None = Field(None, title='Page', ge=1, le=2147483647, description='Page number (1-indexed, default: 1)')
    limit: int | None = Field(None, title='Limit', ge=1, le=1000, description='Items per page (default: 100, max: 1000)')
    startingAfter: int | None = Field(None, title='Startingafter', description='Cursor for next page (optional, for cursor-based pagination)')

class ListProspects(OperationBase):
    operation: Literal["list_prospects"] = Field("list_prospects", title='List Prospects')
    email: str | None = Field(None, title='Email', description='Filter by exact email match (used for email-to-ID lookup)')
    status: Literal['Unknown', 'EspMatchNotFound', 'EspNotAllowed', 'NoWarmup', 'NotReceiving', 'WarmupLimits', 'SendingLimits', 'NoSender', 'Stuck', 'MailboxInexistent', 'EmptySubject', 'EmptyBody', 'MissingPlaceholder', 'Invalid', 'Blacklisted', 'Stopped', 'Unsub', 'BounceHard', 'BounceSoft', 'AutoNolonger', 'AutoOoo', 'AutoReply', 'CollegueReplied', 'SenderDisconnected', 'Paused', 'InsufficientCredit', 'ScheduleInactive', 'NotInterested', 'NotSet', 'Neutral', 'MaybeLater', 'Interested', 'MeetingBooked', 'MeetingCompleted', 'Won', 'Subbed'] | None = Field(None, title='Status', description='Filter by CRM status')
    tags: str | None = Field(None, title='Tags', description='Filter by tags (comma-separated)')
    search: str | None = Field(None, title='Search', description='Search in email, first name, last name')
    validationStatus: Literal['Unvalidated', 'Valid', 'Invalid', 'CatchAll', 'Disposable', 'Unknown'] | None = Field(None, title='Validationstatus', description='Filter by email validation verdict (Unvalidated, Valid, Invalid, CatchAll, Disposable, Unknown)')
    page: int | None = Field(None, title='Page', ge=1, le=2147483647, description='Page number (1-indexed, default: 1)')
    limit: int | None = Field(None, title='Limit', ge=1, le=1000, description='Items per page (default: 100, max: 1000)')
    startingAfter: int | None = Field(None, title='Startingafter', description='Cursor for next page (optional, for cursor-based pagination)')

class CreateProspect(OperationBase):
    operation: Literal["create_prospect"] = Field("create_prospect", title='Create Prospect')
    email: str = Field(..., title='Email', min_length=0, max_length=256, description='Email address of the prospect; must be valid email format with maximum 256 characters.')
    firstName: str | None = Field(None, title='Firstname', min_length=0, max_length=512, description="Prospect's first name for personalization; maximum 512 characters.")
    lastName: str | None = Field(None, title='Lastname', min_length=0, max_length=512, description="Prospect's last name for personalization; maximum 512 characters.")
    company: str | None = Field(None, title='Company', min_length=0, max_length=512, description='Company name where the prospect works; maximum 512 characters.')
    baseListId: int | None = Field(None, title='Baselistid', ge=1, le=2147483647, description='Optional ID of the list where the prospect will be added. Use the `/lists` endpoint to create or retrieve a\r\nvalid list ID. Must be a positive integer when provided. If omitted, the prospect is created without being\r\nassigned to a list (ListID defaults to 0 in the database).')

class GetProspect(OperationBase):
    operation: Literal["get_prospect"] = Field("get_prospect", title='Get Prospect')
    id: int = Field(..., title='Id', ge=1, le=2147483647)

class UpdateProspect(OperationBase):
    operation: Literal["update_prospect"] = Field("update_prospect", title='Update Prospect')
    id: int = Field(..., title='Id', ge=1, le=2147483647)
    firstName: str | None = Field(None, title='Firstname', description="Prospect's first name for personalization; maximum 512 characters.")
    lastName: str | None = Field(None, title='Lastname', description="Prospect's last name for personalization; maximum 512 characters.")
    company: str | None = Field(None, title='Company', description='Company name where the prospect works; maximum 512 characters.')
    sendingStatus: Literal['Unknown', 'EspMatchNotFound', 'EspNotAllowed', 'NoWarmup', 'NotReceiving', 'WarmupLimits', 'SendingLimits', 'NoSender', 'Stuck', 'MailboxInexistent', 'EmptySubject', 'EmptyBody', 'MissingPlaceholder', 'Invalid', 'Blacklisted', 'Stopped', 'Unsub', 'BounceHard', 'BounceSoft', 'AutoNolonger', 'AutoOoo', 'AutoReply', 'CollegueReplied', 'SenderDisconnected', 'Paused', 'InsufficientCredit', 'ScheduleInactive', 'NotInterested', 'NotSet', 'Neutral', 'MaybeLater', 'Interested', 'MeetingBooked', 'MeetingCompleted', 'Won', 'Subbed'] | None = Field(None, title='Sendingstatus', description="Current sending status code indicating the prospect's campaign participation state.")
    sendingActive: bool | None = Field(None, title='Sendingactive', description='Indicates whether the prospect is active and eligible for sending in campaigns.')
    notes: str | None = Field(None, title='Notes', description='General notes or comments about this prospect for internal reference.')

class DeleteProspect(OperationBase):
    operation: Literal["delete_prospect"] = Field("delete_prospect", title='Delete Prospect')
    id: int = Field(..., title='Id', ge=1, le=2147483647)

class ListProspectMessages(OperationBase):
    operation: Literal["list_prospect_messages"] = Field("list_prospect_messages", title='List Prospect Messages')
    id: int = Field(..., title='Id', ge=1, le=2147483647)
    page: int | None = Field(None, title='Page', ge=1, le=2147483647, description='Page number (1-indexed, default: 1)')
    limit: int | None = Field(None, title='Limit', ge=1, le=1000, description='Items per page (default: 100, max: 1000)')
    startingAfter: str | None = Field(None, title='Startingafter', description='Cursor for next page (optional, for cursor-based pagination)')

class AddProspectTag(OperationBase):
    operation: Literal["add_prospect_tag"] = Field("add_prospect_tag", title='Add Prospect Tag')
    id: int = Field(..., title='Id', ge=1, le=2147483647)
    tagId: int = Field(..., title='Tagid', ge=1, le=2147483647, description='Tag ID to add to the prospect')

class ListLists(OperationBase):
    operation: Literal["list_lists"] = Field("list_lists", title='List Lists')
    page: int | None = Field(None, title='Page', ge=1, le=2147483647, description='Page number (1-indexed, default: 1)')
    limit: int | None = Field(None, title='Limit', ge=1, le=1000, description='Items per page (default: 100, max: 1000)')
    startingAfter: int | None = Field(None, title='Startingafter', description='Cursor for next page (optional, for cursor-based pagination)')

class CreateList(OperationBase):
    operation: Literal["create_list"] = Field("create_list", title='Create List')
    title: str = Field(..., title='Title', min_length=0, max_length=256, description='Display name of the mailing list; maximum 256 characters.')
    description: str | None = Field(None, title='Description', min_length=0, max_length=4000, description='Optional description explaining the purpose or source of this list; maximum 4,000 characters.')
    folderId: int | None = Field(None, title='Folderid', ge=1, le=2147483647, description='Folder identifier for organizing and grouping lists; must be a positive integer.')

class GetList(OperationBase):
    operation: Literal["get_list"] = Field("get_list", title='Get List')
    id: int = Field(..., title='Id', ge=1, le=2147483647)

class ListSenders(OperationBase):
    operation: Literal["list_senders"] = Field("list_senders", title='List Senders')
    folder: str | None = Field(None, title='Folder', description='Filter by folder name.')
    status: str | None = Field(None, title='Status', description='Filter by status: "error" (disconnected senders) or "blacklisted" (sender email domain currently listed by the daily blacklist scan; requires Blacklist Monitoring, otherwise the list is empty).')
    warmup: bool | None = Field(None, title='Warmup', description='Filter by warmup status.')
    search: str | None = Field(None, title='Search', description='Search by text (first/last/email).')
    page: int | None = Field(None, title='Page', ge=1, le=2147483647, description='Page number (1-indexed, default: 1)')
    limit: int | None = Field(None, title='Limit', ge=1, le=1000, description='Items per page (default: 100, max: 1000)')
    startingAfter: int | None = Field(None, title='Startingafter', description='Cursor for next page (optional, for cursor-based pagination)')

class GetSender(OperationBase):
    operation: Literal["get_sender"] = Field("get_sender", title='Get Sender')
    id: int = Field(..., title='Id', ge=1, le=2147483647)

class ListTags(OperationBase):
    operation: Literal["list_tags"] = Field("list_tags", title='List Tags')
    search: str | None = Field(None, title='Search', description='Optional case-insensitive search term for tag name')
    tagType: str | None = Field(None, title='Tagtype', description='Optional filter: Crm, Campaign, or Sender (matches EM_TAG.TagType)')
    include: str | None = Field(None, title='Include', description='Comma-separated list of additional data to include (e.g., "prospectCount")')
    page: int | None = Field(None, title='Page', ge=1, le=2147483647, description='Page number (1-indexed, default: 1)')
    limit: int | None = Field(None, title='Limit', ge=1, le=1000, description='Items per page (default: 100, max: 1000)')
    startingAfter: int | None = Field(None, title='Startingafter', description='Cursor for next page (optional, for cursor-based pagination)')

class CreateTag(OperationBase):
    operation: Literal["create_tag"] = Field("create_tag", title='Create Tag')
    title: str = Field(..., title='Title', min_length=0, max_length=128, description='Tag name used for organizing and categorizing prospects; required. Maximum 128 characters.')
    description: str | None = Field(None, title='Description', min_length=0, max_length=1000, description='Optional description explaining the purpose or criteria for this tag; maximum 1,000 characters.')
    tagType: Literal['Campaign', 'Crm', 'Sender'] | None = Field(None, title='Tagtype', description='Tag classification: Crm (prospect/CRM), Campaign, or Sender. Defaults to Crm for new API tags.')

class GetTag(OperationBase):
    operation: Literal["get_tag"] = Field("get_tag", title='Get Tag')
    id: int = Field(..., title='Id', ge=1, le=2147483647)

class CheckBlacklistedEmail(OperationBase):
    operation: Literal["check_blacklisted_email"] = Field("check_blacklisted_email", title='Check Blacklisted Email')
    email: str = Field(..., title='Email', description='Parameter: email')

Operation = Annotated[Union[GetAccount, GetCredits, ListCampaigns, CreateCampaign, GetCampaign, PauseCampaign, StartCampaign, GetCampaignStats, ListCampaignProspects, ListProspects, CreateProspect, GetProspect, UpdateProspect, DeleteProspect, ListProspectMessages, AddProspectTag, ListLists, CreateList, GetList, ListSenders, GetSender, ListTags, CreateTag, GetTag, CheckBlacklistedEmail], Field(discriminator="operation")]

class ManyreachNodeConfig(NodeConfig[Operation, ManyreachApiKey]):
    pass

ROUTES = {'get_account': ('GET', '/account', [], []), 'get_credits': ('GET', '/account/credits', [], []), 'list_campaigns': ('GET', '/campaigns', [('includeArchived', 'pageQuery.includeArchived'), ('status', 'pageQuery.status'), ('page', 'pageQuery.page'), ('limit', 'pageQuery.limit'), ('startingAfter', 'pageQuery.startingAfter')], []), 'create_campaign': ('POST', '/campaigns', [], ['name', 'description', 'subject', 'body', 'fromEmails', 'dailyLimit']), 'get_campaign': ('GET', '/campaigns/{id}', [], []), 'pause_campaign': ('POST', '/campaigns/{id}/pause', [], []), 'start_campaign': ('POST', '/campaigns/{id}/start', [], []), 'get_campaign_stats': ('GET', '/campaigns/{id}/stats', [('dateStart', 'dateStart'), ('dateEnd', 'dateEnd'), ('refresh', 'refresh')], []), 'list_campaign_prospects': ('GET', '/campaigns/{id}/prospects', [('sendingStatus', 'sendingStatus'), ('sendingActive', 'sendingActive'), ('page', 'page'), ('limit', 'limit'), ('startingAfter', 'startingAfter')], []), 'list_prospects': ('GET', '/prospects', [('email', 'email'), ('status', 'status'), ('tags', 'tags'), ('search', 'search'), ('validationStatus', 'validationStatus'), ('page', 'page'), ('limit', 'limit'), ('startingAfter', 'startingAfter')], []), 'create_prospect': ('POST', '/prospects', [], ['email', 'firstName', 'lastName', 'company', 'baseListId']), 'get_prospect': ('GET', '/prospects/{id}', [], []), 'update_prospect': ('PATCH', '/prospects/{id}', [], ['firstName', 'lastName', 'company', 'sendingStatus', 'sendingActive', 'notes']), 'delete_prospect': ('DELETE', '/prospects/{id}', [], []), 'list_prospect_messages': ('GET', '/prospects/{id}/messages', [('page', 'page'), ('limit', 'limit'), ('startingAfter', 'startingAfter')], []), 'add_prospect_tag': ('POST', '/prospects/{id}/tags', [], ['tagId']), 'list_lists': ('GET', '/lists', [('page', 'page'), ('limit', 'limit'), ('startingAfter', 'startingAfter')], []), 'create_list': ('POST', '/lists', [], ['title', 'description', 'folderId']), 'get_list': ('GET', '/lists/{id}', [], []), 'list_senders': ('GET', '/senders', [('folder', 'folder'), ('status', 'status'), ('warmup', 'warmup'), ('search', 'search'), ('page', 'page'), ('limit', 'limit'), ('startingAfter', 'startingAfter')], []), 'get_sender': ('GET', '/senders/{id}', [], []), 'list_tags': ('GET', '/tags', [('search', 'search'), ('tagType', 'tagType'), ('include', 'include'), ('page', 'page'), ('limit', 'limit'), ('startingAfter', 'startingAfter')], []), 'create_tag': ('POST', '/tags', [], ['title', 'description', 'tagType']), 'get_tag': ('GET', '/tags/{id}', [], []), 'check_blacklisted_email': ('GET', '/blacklist/emails/check', [('email', 'email')], [])}

class ManyreachNode(WorkflowNode):
    integration_type = "automation-manyreach"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account", label_keys=("title", "id"))

    @classmethod
    def get_config_model(cls):
        return ManyreachNodeConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a Manyreach API key")
        op = self.config.config
        method, path, query_fields, body_fields = ROUTES[op.operation]
        if "{id}" in path:
            path = path.replace("{id}", str(op.id))
        params = {wire: getattr(op, key) for key, wire in query_fields if getattr(op, key) is not None}
        body = {key: getattr(op, key) for key in body_fields if getattr(op, key) is not None}
        key = self.config.credentials.api_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.manyreach.com/api/v2" + path,
                headers={"X-API-Key": key, "Accept": "application/json"}, params=params,
                **({"json": body} if body_fields else {}))
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for connection evidence, without leaking the key.
            raise ValueError(f"Manyreach HTTP {response.status_code}: " + response.text.replace(key, "[redacted]"))
        data = response.json() if response.content else None
        result = {"data": data, "http_status": response.status_code}
        await self.emit(result)
        return result

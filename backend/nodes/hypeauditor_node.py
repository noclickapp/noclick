"""HypeAuditor public API v1: explicit single-page reads and media-plan writes.

Contract: https://hypeauditor.com/swagger/public-api/v1/openapi.json (1.0).
One request per operation. Unlocking emails spends provider tokens. Batch writes
preserve added/deleted/skipped results and never imply every item succeeded.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

import json

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://hypeauditor.com"


class HypeAuditorAPIToken(BaseModel):
    model_config = ConfigDict(title="HypeAuditor API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://hypeauditor.com/api-integration/",
            "x-credential-instructions": "Paste the Client ID and API token supplied by HypeAuditor for REST API access. NoClick sends them as X-Auth-Id and X-Auth-Hash. Connecting reads your saved media plans; endpoint availability and credits depend on your plan. Unlocking creator emails spends unlock tokens.",
        })
    credential_type: Literal["hypeauditor_api_token"] = Field("hypeauditor_api_token", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., title="Client ID", min_length=1, max_length=20, pattern=r"^[0-9]+$", description="The numeric authorized user / Client ID supplied with your API token.")
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class HypeAuditorCheckReportUnlockConfigReportsItem(_Input):
    social_type: str = Field(..., description='Social network type')
    social_id: str | None = Field(None, description='Unique social network ID of the influencer')
    username: str | None = Field(None, description='Username of the influencer (used if social_id is not provided)')


    @model_validator(mode="after")
    def identity(self):
        if not self.social_id and not self.username:
            raise ValueError("Provide social_id or username")
        return self


class HypeAuditorUnlockCreatorEmailsConfigCreatorsItem(_Input):
    social_type: str = Field(..., description='Social network type')
    social_id: str = Field(..., description='Unique social network ID of the creator')


class HypeAuditorAddPlanAccountsConfigAccountsItem(_Input):
    social_type: Literal['instagram', 'youtube', 'tiktok'] = Field(..., description='Social network type')
    social_id: str | None = Field(None, max_length=256, description='Social network account ID. At least one of social_id or username must be provided')
    username: str | None = Field(None, max_length=256, description='Account username. At least one of social_id or username must be provided')


    @model_validator(mode="after")
    def identity(self):
        if not self.social_id and not self.username:
            raise ValueError("Provide social_id or username")
        return self


class HypeAuditorDeletePlanAccountsConfigAccountsItem(_Input):
    social_type: Literal['instagram', 'youtube', 'tiktok'] = Field(..., description='Social network type')
    social_id: str = Field(..., max_length=128, description='Social network account ID')


class HypeAuditorGetLookalikesConfig(_Input):
    'Find similar creators accounts based on provided usernames or social IDs. Results are returned synchronously.'
    operation: Literal['get_lookalikes'] = Field('get_lookalikes', json_schema_extra={"x-operation-kind": 'read'})
    social_type: Literal['instagram', 'youtube', 'tiktok'] = Field(..., description='Social network type')
    usernames: list[str] | None = Field(None, description='Array of usernames (required for Instagram and TikTok). Not used for YouTube.')
    social_ids: list[str] | None = Field(None, description='Array of social network IDs (required for YouTube, e.g., channel IDs). Not used for Instagram/TikTok.')
    page: int = Field(1, ge=1, description='Page number for pagination')
    limit: int = Field(20, ge=1, le=100, description='Number of items per page')
    @model_validator(mode="after")
    def seeds(self):
        if self.social_type == "youtube":
            if not self.social_ids or self.usernames:
                raise ValueError("YouTube requires social_ids, without usernames")
        elif not self.usernames or self.social_ids:
            raise ValueError("Instagram and TikTok require usernames, without social_ids")
        return self



class HypeAuditorListListenersConfig(_Input):
    'Retrieve a paginated list of all social listening listeners. Returns listeners with their current status, creator counts, and monitoring information.'
    operation: Literal['list_listeners'] = Field('list_listeners', json_schema_extra={"x-operation-kind": 'read'})
    page: int = Field(1, ge=1, description='Page number for pagination')
    limit: int = Field(5, ge=1, le=10, description='Number of items per page (maximum 10)')


class HypeAuditorCreateListenerConfig(_Input):
    'Create a new social listening listener to track mentions, hashtags, or keywords across Instagram and TikTok. The listener will continuously monitor the specified value and collect posts from creators who use it.'
    operation: Literal['create_listener'] = Field('create_listener', json_schema_extra={"x-operation-kind": 'write'})
    value: str = Field(..., max_length=255, description="The value to monitor. For 'mention' type: username without @. For 'tag' type: hashtag without #. For 'keyword' type: any text string.")
    type: Literal['mention', 'tag', 'keyword'] = Field(..., description='Type of listener value')
    social_types: list[Literal['instagram', 'tiktok']] = Field(..., min_length=1, description='Array of social networks to monitor (at least one required)')


class HypeAuditorGetCreatorMentionsConfig(_Input):
    'Retrieve all posts (mentions) from a specific creator discovered through social listening. Returns posts where the creator mentioned tracked usernames, hashtags, or keywords across Instagram and TikTok. Results can be optionally filtered by a specific listener.'
    operation: Literal['get_creator_mentions'] = Field('get_creator_mentions', json_schema_extra={"x-operation-kind": 'read'})
    creator_id: int = Field(..., description='Creator unique identifier from the social listening creators list')
    listener_id: str | None = Field(None, description='Filter posts by specific listener ID. If not provided, returns all posts from all listeners for this creator.')


class HypeAuditorListCreatorsConfig(_Input):
    'Retrieve a paginated list of creators discovered through social listening. Returns creators who have mentioned tracked usernames, hashtags, or keywords across Instagram and TikTok. Results can be filtered by specific listener and sorted by discovery date.'
    operation: Literal['list_creators'] = Field('list_creators', json_schema_extra={"x-operation-kind": 'read'})
    page: int = Field(1, ge=1, description='Page number for pagination')
    limit: int = Field(20, ge=1, le=100, description='Number of items per page')
    sort_order: Literal['asc', 'desc'] = Field('desc', description='Sort order by discovery date (asc - oldest first, desc - newest first)')
    listener_id: str | None = Field(None, description='Filter creators by specific listener ID. If not provided, returns creators from all listeners.')
    with_disabled_listeners: bool = Field(False, description='Include creators from disabled listeners in results')


class HypeAuditorCheckReportUnlockConfig(_Input):
    'Returns the unlock status for each requested influencer report, identified by social_type and social_id or username.'
    operation: Literal['check_report_unlock'] = Field('check_report_unlock', json_schema_extra={"x-operation-kind": 'read'})
    reports: list[HypeAuditorCheckReportUnlockConfigReportsItem] = Field(..., min_length=1, max_length=100, description='List of influencer accounts to check (1–100 items)')


class HypeAuditorUnlockCreatorEmailsConfig(_Input):
    'Unlocks and returns email addresses for each requested creator, identified by social_type and social_id. Spends unlock tokens when an email is unlocked.'
    operation: Literal['unlock_creator_emails'] = Field('unlock_creator_emails', json_schema_extra={"x-operation-kind": 'write'})
    creators: list[HypeAuditorUnlockCreatorEmailsConfigCreatorsItem] = Field(..., min_length=1, max_length=50, description='List of creators to unlock emails for (1–50 items)')


class HypeAuditorListPlanAccountsConfig(_Input):
    'Returns a paginated list of creators’ social network accounts for a specific media plan'
    operation: Literal['list_plan_accounts'] = Field('list_plan_accounts', json_schema_extra={"x-operation-kind": 'read'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')
    page: int = Field(1, ge=1, description='Page number')
    limit: int = Field(10, ge=1, le=20, description='Number of items per page')
    social_type: Literal['instagram', 'youtube', 'tiktok'] | None = Field(None, description='Filter by social network type')
    social_id: str | None = Field(None, description='Filter by social network account ID')


class HypeAuditorAddPlanAccountsConfig(_Input):
    'Adds social network accounts to a specific media plan. Accepts up to 20 accounts per request'
    operation: Literal['add_plan_accounts'] = Field('add_plan_accounts', json_schema_extra={"x-operation-kind": 'write'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')
    accounts: list[HypeAuditorAddPlanAccountsConfigAccountsItem] = Field(..., max_length=20, description='Array of accounts to add')


class HypeAuditorDeletePlanAccountsConfig(_Input):
    'Deletes accounts from a specific media plan. Accepts up to 20 accounts per request. Accounts that are not found in the plan will be listed in the skipped array.'
    operation: Literal['delete_plan_accounts'] = Field('delete_plan_accounts', json_schema_extra={"x-operation-kind": 'write'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')
    accounts: list[HypeAuditorDeletePlanAccountsConfigAccountsItem] = Field(..., max_length=20, description='Array of accounts to delete')


class HypeAuditorListPlanCreatorsConfig(_Input):
    'Returns a paginated list of creators for a specific media plan, including their social network accounts in a compact format. Each creator may be associated with multiple social network accounts.'
    operation: Literal['list_plan_creators'] = Field('list_plan_creators', json_schema_extra={"x-operation-kind": 'read'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')
    page: int = Field(1, ge=1, description='Page number')
    limit: int = Field(10, ge=1, le=20, description='Number of items per page')
    state: Literal['in_review', 'accepted', 'rejected'] | None = Field(None, description='Filter by creator state')


class HypeAuditorDeletePlanEventConfig(_Input):
    'Deletes a specific event from a media plan.'
    operation: Literal['delete_plan_event'] = Field('delete_plan_event', json_schema_extra={"x-operation-kind": 'write'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')
    eventId: str = Field(..., min_length=1, max_length=255, description='Event unique identifier (UUID)')


class HypeAuditorListPlanEventsConfig(_Input):
    'Retrieves a paginated list of events for a specific social network account in a media plan.'
    operation: Literal['list_plan_events'] = Field('list_plan_events', json_schema_extra={"x-operation-kind": 'read'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')
    social_type: Literal['instagram', 'youtube', 'tiktok'] = Field(..., description='Social network type')
    social_id: str = Field(..., description='Social network account ID')
    page: int = Field(1, ge=1, description='Page number (default: 1)')
    limit: int = Field(10, ge=1, le=100, description='Items per page (default: 10, max: 100)')


class HypeAuditorCreatePlanEventConfig(_Input):
    'Creates a new comment event for a specific social network account in a media plan.'
    operation: Literal['create_plan_event'] = Field('create_plan_event', json_schema_extra={"x-operation-kind": 'write'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')
    type: Literal['comment'] = Field('comment', description='Event type')
    value: str = Field(..., description='Event content (comment text)')
    social_type: Literal['instagram', 'youtube', 'tiktok'] = Field(..., description='Social network type')
    social_id: str = Field(..., max_length=255, description='Social network account ID')


class HypeAuditorListMediaPlansConfig(_Input):
    'Returns a paginated list of media plans'
    operation: Literal['list_media_plans'] = Field('list_media_plans', json_schema_extra={"x-operation-kind": 'read'})
    page: int = Field(1, ge=1, description='Page number')
    limit: int = Field(10, ge=1, le=100, description='Number of items per page')
    order_by: Literal['events', 'created_at'] | None = Field(None, description='Sort order for the results')


class HypeAuditorCreateMediaPlanConfig(_Input):
    'Creates a new media plan'
    operation: Literal['create_media_plan'] = Field('create_media_plan', json_schema_extra={"x-operation-kind": 'write'})
    title: str | None = Field(None, max_length=128, description='Title for the new media plan (max 128 characters)')


class HypeAuditorGetMediaPlanConfig(_Input):
    'Returns a single media plan with full details including configuration and creators states count'
    operation: Literal['get_media_plan'] = Field('get_media_plan', json_schema_extra={"x-operation-kind": 'read'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')


class HypeAuditorDeleteMediaPlanConfig(_Input):
    'Deletes a media plan by its identifier'
    operation: Literal['delete_media_plan'] = Field('delete_media_plan', json_schema_extra={"x-operation-kind": 'write'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan identifier')


class HypeAuditorUpdateMediaPlanConfig(_Input):
    'Updates an existing media plan with the provided data. All top-level fields are optional: if not provided - field will not be updated, if null is provided - null will be written.'
    operation: Literal['update_media_plan'] = Field('update_media_plan', json_schema_extra={"x-operation-kind": 'write'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')
    title: str | None = Field(None, max_length=128, description='Title for the media plan (max 128 characters). If not provided - field will not be updated. If null is provided - null will be written.')
    description: str | None = Field(None, max_length=10000, description='Description for the media plan (max 10000 characters). If not provided - field will not be updated. If null is provided - null will be written.')


class HypeAuditorGetMediaPlanMetricsConfig(_Input):
    'Returns aggregated metrics for a media plan including overall metrics and metrics broken down by social network (Instagram, YouTube, TikTok)'
    operation: Literal['get_media_plan_metrics'] = Field('get_media_plan_metrics', json_schema_extra={"x-operation-kind": 'read'})
    planId: str = Field(..., min_length=1, max_length=255, description='Media plan unique identifier')


HypeAuditorConfig = Annotated[Union[
    HypeAuditorGetLookalikesConfig,
    HypeAuditorListListenersConfig,
    HypeAuditorCreateListenerConfig,
    HypeAuditorGetCreatorMentionsConfig,
    HypeAuditorListCreatorsConfig,
    HypeAuditorCheckReportUnlockConfig,
    HypeAuditorUnlockCreatorEmailsConfig,
    HypeAuditorListPlanAccountsConfig,
    HypeAuditorAddPlanAccountsConfig,
    HypeAuditorDeletePlanAccountsConfig,
    HypeAuditorListPlanCreatorsConfig,
    HypeAuditorDeletePlanEventConfig,
    HypeAuditorListPlanEventsConfig,
    HypeAuditorCreatePlanEventConfig,
    HypeAuditorListMediaPlansConfig,
    HypeAuditorCreateMediaPlanConfig,
    HypeAuditorGetMediaPlanConfig,
    HypeAuditorDeleteMediaPlanConfig,
    HypeAuditorUpdateMediaPlanConfig,
    HypeAuditorGetMediaPlanMetricsConfig
], Field(discriminator="operation")]


class HypeAuditorFullConfig(NodeConfig[HypeAuditorConfig, HypeAuditorAPIToken]):
    pass


# method, fixed path, path fields, query names, JSON fields
ROUTES = {
    'get_lookalikes': ('GET', '/api/v1/look-alike/usernames', [], {'social_type': 'social_type', 'usernames': 'usernames[]', 'social_ids': 'social_ids[]', 'page': 'page', 'limit': 'limit'}, []),
    'list_listeners': ('GET', '/api/v1/social-listening/listeners', [], {'page': 'page', 'limit': 'limit'}, []),
    'create_listener': ('POST', '/api/v1/social-listening/listeners', [], {}, ['value', 'type', 'social_types']),
    'get_creator_mentions': ('GET', '/api/v1/social-listening/creators/{creator_id}/mentions', ['creator_id'], {'listener_id': 'listener_id'}, []),
    'list_creators': ('GET', '/api/v1/social-listening/creators', [], {'page': 'page', 'limit': 'limit', 'sort_order': 'sort_order', 'listener_id': 'listener_id', 'with_disabled_listeners': 'with_disabled_listeners'}, []),
    'check_report_unlock': ('POST', '/api/v1/report/check-unlock', [], {}, ['reports']),
    'unlock_creator_emails': ('POST', '/api/v1/report/unlock-emails', [], {}, ['creators']),
    'list_plan_accounts': ('GET', '/api/v1/media-plan/plans/{planId}/accounts', ['planId'], {'page': 'page', 'limit': 'limit', 'social_type': 'social_type', 'social_id': 'social_id'}, []),
    'add_plan_accounts': ('POST', '/api/v1/media-plan/plans/{planId}/accounts', ['planId'], {}, ['accounts']),
    'delete_plan_accounts': ('DELETE', '/api/v1/media-plan/plans/{planId}/accounts', ['planId'], {}, ['accounts']),
    'list_plan_creators': ('GET', '/api/v1/media-plan/plans/{planId}/creators', ['planId'], {'page': 'page', 'limit': 'limit', 'state': 'state'}, []),
    'delete_plan_event': ('DELETE', '/api/v1/media-plan/plans/{planId}/events/{eventId}', ['planId', 'eventId'], {}, []),
    'list_plan_events': ('GET', '/api/v1/media-plan/plans/{planId}/events', ['planId'], {'social_type': 'social_type', 'social_id': 'social_id', 'page': 'page', 'limit': 'limit'}, []),
    'create_plan_event': ('POST', '/api/v1/media-plan/plans/{planId}/events', ['planId'], {}, ['type', 'value', 'social_type', 'social_id']),
    'list_media_plans': ('GET', '/api/v1/media-plan/plans', [], {'page': 'page', 'limit': 'limit', 'order_by': 'order_by'}, []),
    'create_media_plan': ('POST', '/api/v1/media-plan/plans', [], {}, ['title']),
    'get_media_plan': ('GET', '/api/v1/media-plan/plans/{planId}', ['planId'], {}, []),
    'delete_media_plan': ('DELETE', '/api/v1/media-plan/plans/{planId}', ['planId'], {}, []),
    'update_media_plan': ('PATCH', '/api/v1/media-plan/plans/{planId}', ['planId'], {}, ['title', 'description']),
    'get_media_plan_metrics': ('GET', '/api/v1/media-plan/plans/{planId}/metrics', ['planId'], {}, []),
}


class HypeAuditorNode(WorkflowNode):
    integration_type = "automation-hypeauditor"
    connection_evidence = ConnectionEvidence(noun="media plans", operation="list_media_plans")

    @classmethod
    def get_config_model(cls):
        return HypeAuditorFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a HypeAuditor API token")
        config = self.config.config
        method, route, path_fields, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for field in path_fields:
            value = str(values[field])
            if value in {".", ".."} or any(c in value for c in "/?#\\"):
                raise ValueError("Use a single HypeAuditor resource ID")
            route = route.replace("{" + field + "}", quote(value, safe=""))
        params = []
        for field, wire_name in query_fields.items():
            value = values.get(field)
            if value is None:
                continue
            for item in value if isinstance(value, list) else [value]:
                params.append((wire_name, str(item).lower() if isinstance(item, bool) else str(item)))
        # Explicit nulls clear title/description on PATCH; omitted fields stay omitted.
        sent = config.model_dump(exclude_unset=True, exclude_none=config.operation != "update_media_plan", exclude={"operation"})
        body = {k: sent[k] if k in sent else values[k] for k in body_fields if k in sent or k in values} if body_fields else None
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, params=params, **({"json": body} if body is not None else {}),
                    headers={"X-Auth-Id": credential.client_id, "X-Auth-Hash": credential.api_token,
                             "Accept": "application/json"})
        except httpx.HTTPError:
            return {"status": "error", "error": "HypeAuditor request could not be completed; inspect writes before retrying"}
        if response.status_code == 204 and config.operation in {"delete_media_plan", "delete_plan_event"}:
            return {"status": "success", "http_status": 204, "deletion_acknowledged": True}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "HypeAuditor returned invalid JSON"}
        if response.status_code != 200 or not isinstance(payload, dict) or "result" not in payload or payload.get("error"):
            message = json.dumps(payload, ensure_ascii=False).replace(credential.api_token, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        result = payload["result"]
        if not isinstance(result, (dict, list)):
            return {"status": "error", "error": "HypeAuditor returned an unexpected result"}
        return {"status": "success", "http_status": response.status_code, "result": result,
                **({"page": values["page"], "limit": values["limit"]} if "page" in values and "limit" in values else {})}

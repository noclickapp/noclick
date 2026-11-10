"""Ringover Public API v2.1.0. Routes and event shapes follow the published OpenAPI contract."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote
import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

class RingoverAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Ringover API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.ringover.com/developer",
        "x-credential-instructions": "In Ringover Dashboard, open Developer, create an API key for your user, then edit its rights to allow the reads and writes you need. Paste the key here. Choose the region of your team."})
    credential_type: Literal["ringover_api_key"] = Field("ringover_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"})
    region: Literal["Europe", "United States"] = Field("Europe", title="Region")

class RingoverGetTeamConfig(BaseModel):
    operation: Literal['get_team'] = Field('get_team', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get team information', "x-category": 'Teams', "x-is-trigger": False})

class RingoverListUsersConfig(BaseModel):
    operation: Literal['list_users'] = Field('list_users', json_schema_extra={"ui:hidden": True, "x-display-name": 'List all team users', "x-category": 'Users', "x-is-trigger": False})

class RingoverGetUserConfig(BaseModel):
    operation: Literal['get_user'] = Field('get_user', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a user by ID', "x-category": 'Users', "x-is-trigger": False})
    userId: int = Field(..., title='Userid')

class RingoverListNumbersConfig(BaseModel):
    operation: Literal['list_numbers'] = Field('list_numbers', json_schema_extra={"ui:hidden": True, "x-display-name": 'List team phone numbers', "x-category": 'Numbers', "x-is-trigger": False})
    is_user: bool = Field(False, title='Is User')
    is_ivr: bool = Field(False, title='Is Ivr')
    is_fax: bool = Field(False, title='Is Fax')
    is_conference: bool = Field(False, title='Is Conference')
    is_available: bool = Field(True, title='Is Available')

class RingoverListCallsConfig(BaseModel):
    operation: Literal['list_calls'] = Field('list_calls', json_schema_extra={"ui:hidden": True, "x-display-name": 'List terminated calls', "x-category": 'Calls', "x-is-trigger": False})
    start_date: Optional[str] = Field(None, title='Start Date')
    end_date: Optional[str] = Field(None, title='End Date')
    limit_count: int = Field(100, title='Limit Count', ge=1, le=1000)
    limit_offset: int = Field(0, title='Limit Offset', ge=0, le=9000)
    last_id_returned: Optional[int] = Field(None, title='Last Id Returned')
    call_type: Optional[Literal['ANSWERED', 'MISSED', 'OUT', 'VOICEMAIL']] = Field(None, title='Call Type')
    ascending_order: Optional[bool] = Field(None, title='Ascending Order')
    expand: Optional[list[Literal['summary', 'transcription']]] = Field(None, title='Expand')

class RingoverGetCallConfig(BaseModel):
    operation: Literal['get_call'] = Field('get_call', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a specific call by ID', "x-category": 'Calls', "x-is-trigger": False})
    callId: str = Field(..., title='Callid')

class RingoverArchiveCallConfig(BaseModel):
    operation: Literal['archive_call'] = Field('archive_call', json_schema_extra={"ui:hidden": True, "x-display-name": 'Archive a call by call ID', "x-category": 'Calls', "x-is-trigger": False})
    callId: str = Field(..., title='Callid')

class RingoverListContactsConfig(BaseModel):
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True, "x-display-name": 'List your contacts', "x-category": 'Contacts', "x-is-trigger": False})
    pagination: Optional[str] = Field(None, title='Pagination')
    alphabetical_order: Optional[str] = Field(None, title='Alphabetical Order')
    search: Optional[str] = Field(None, title='Search')
    limit_count: Optional[int] = Field(None, title='Limit Count', le=500)
    limit_offset: Optional[int] = Field(None, title='Limit Offset')

class RingoverGetContactConfig(BaseModel):
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a specific contact', "x-category": 'Contacts', "x-is-trigger": False})
    contactId: int = Field(..., title='Contactid')

class RingoverUpdateContactConfig(BaseModel):
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update a contact', "x-category": 'Contacts', "x-is-trigger": False})
    contactId: int = Field(..., title='Contactid')
    firstname: Optional[str] = Field(None, title='Firstname')
    lastname: Optional[str] = Field(None, title='Lastname')
    company: Optional[str] = Field(None, title='Company')
    is_shared: Optional[bool] = Field(None, title='Is Shared')
    numbers: Optional[list[dict[str, Any]]] = Field(None, title='Numbers')

class RingoverDeleteContactConfig(BaseModel):
    operation: Literal['delete_contact'] = Field('delete_contact', json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete a contact', "x-category": 'Contacts', "x-is-trigger": False})
    contactId: int = Field(..., title='Contactid')

class RingoverListTagsConfig(BaseModel):
    operation: Literal['list_tags'] = Field('list_tags', json_schema_extra={"ui:hidden": True, "x-display-name": 'List all call tags', "x-category": 'Tags', "x-is-trigger": False})

class RingoverCreateTagConfig(BaseModel):
    operation: Literal['create_tag'] = Field('create_tag', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create a new call tag', "x-category": 'Tags', "x-is-trigger": False})
    name: Optional[str] = Field(None, title='Name')
    color: Optional[Literal['ff6b6b', 'F06292', 'BA68C8', '9575CD', '7986CB', '64B5F6', '4FC3F7', '4DD0E1', '4DB6AC', '81C784', 'AED581', 'DCE775', 'FFD54F', 'FFB74D', 'FF8A65', 'A1887F', 'E0E0E0', '90A4AE']] = Field(None, title='Color')
    description: Optional[str] = Field(None, title='Description')

class RingoverListConversationsConfig(BaseModel):
    operation: Literal['list_conversations'] = Field('list_conversations', json_schema_extra={"ui:hidden": True, "x-display-name": 'List conversations', "x-category": 'Conversations', "x-is-trigger": False})
    filter: Optional[list[Literal['ALL', 'INTERNAL', 'EXTERNAL', 'COLLABORATIVE']]] = Field(None, title='Filter')
    limit_count: Optional[int] = Field(None, title='Limit Count', le=1000)
    limit_offset: Optional[int] = Field(None, title='Limit Offset')

class RingoverListMessagesConfig(BaseModel):
    operation: Literal['list_messages'] = Field('list_messages', json_schema_extra={"ui:hidden": True, "x-display-name": 'List messages from a conversation', "x-category": 'Messages', "x-is-trigger": False})
    limit_count: Optional[int] = Field(None, title='Limit Count', le=1000)
    last_id_returned: Optional[int] = Field(None, title='Last Id Returned')
    display_archived: Optional[bool] = Field(None, title='Display Archived')
    convId: int = Field(..., title='Convid')

class RingoverSendSmsConfig(BaseModel):
    operation: Literal['send_sms'] = Field('send_sms', json_schema_extra={"ui:hidden": True, "x-display-name": 'Send an SMS', "x-category": 'Sms', "x-is-trigger": False})
    archived_auto: Optional[bool] = Field(None, title='Archived Auto')
    from_number: str = Field(..., title='From Number')
    to_number: str = Field(..., title='To Number')
    content: str = Field(..., title='Content')
    user_id_forced: Optional[int] = Field(None, title='User Id Forced')
    scheduled_at: Optional[str] = Field(None, title='Scheduled At')

class RingoverStartCallbackConfig(BaseModel):
    operation: Literal['start_callback'] = Field('start_callback', json_schema_extra={"ui:hidden": True, "x-display-name": 'Initiate a callback between two numbers', "x-category": 'Callbacks', "x-is-trigger": False})
    from_number: Optional[int] = Field(None, title='From Number')
    to_number: int = Field(..., title='To Number')
    timeout: int = Field(20, title='Timeout', ge=10, le=300)
    device: Literal['ALL', 'APP', 'WEB', 'SIP', 'MOB', 'EXT'] = Field(..., title='Device')
    clir: bool = Field(False, title='Clir')

class RingoverListTranscriptionsConfig(BaseModel):
    operation: Literal['list_transcriptions'] = Field('list_transcriptions', json_schema_extra={"ui:hidden": True, "x-display-name": 'List call transcriptions', "x-category": 'Transcriptions', "x-is-trigger": False})
    limit_count: int = Field(100, title='Limit Count', le=100)
    limit_offset: Optional[int] = Field(None, title='Limit Offset')
    search: Optional[str] = Field(None, title='Search')
    audio_duration_from: Optional[int] = Field(None, title='Audio Duration From')
    audio_duration_to: Optional[int] = Field(None, title='Audio Duration To')
    created_from: Optional[str] = Field(None, title='Created From')
    created_to: Optional[str] = Field(None, title='Created To')

class RingoverGetTranscriptionConfig(BaseModel):
    operation: Literal['get_transcription'] = Field('get_transcription', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a single transcription by call ID', "x-category": 'Transcriptions', "x-is-trigger": False})
    callId: str = Field(..., title='Callid')

class RingoverListGroupsConfig(BaseModel):
    operation: Literal['list_groups'] = Field('list_groups', json_schema_extra={"ui:hidden": True, "x-display-name": 'List groups', "x-category": 'Groups', "x-is-trigger": False})
    limit_count: int = Field(100, title='Limit Count', le=1000)
    limit_offset: int = Field(0, title='Limit Offset')

OPERATIONS = {'get_team': ('GET', '/teams', [], []), 'list_users': ('GET', '/users', [], []), 'get_user': ('GET', '/users/{userId}', [], []), 'list_numbers': ('GET', '/numbers', ['is_user', 'is_ivr', 'is_fax', 'is_conference', 'is_available'], []), 'list_calls': ('GET', '/calls', ['start_date', 'end_date', 'limit_count', 'limit_offset', 'last_id_returned', 'call_type', 'ascending_order', 'expand'], []), 'get_call': ('GET', '/calls/{callId}', [], []), 'archive_call': ('DELETE', '/calls/{callId}', [], []), 'list_contacts': ('GET', '/contacts', ['pagination', 'alphabetical_order', 'search', 'limit_count', 'limit_offset'], []), 'get_contact': ('GET', '/contacts/{contactId}', [], []), 'update_contact': ('PUT', '/contacts/{contactId}', [], ['firstname', 'lastname', 'company', 'is_shared', 'numbers']), 'delete_contact': ('DELETE', '/contacts/{contactId}', [], []), 'list_tags': ('GET', '/tags', [], []), 'create_tag': ('POST', '/tags', [], ['name', 'color', 'description']), 'list_conversations': ('GET', '/conversations', ['filter', 'limit_count', 'limit_offset'], []), 'list_messages': ('GET', '/conversations/{convId}/messages', ['limit_count', 'last_id_returned', 'display_archived'], []), 'send_sms': ('POST', '/push/sms', [], ['archived_auto', 'from_number', 'to_number', 'content', 'user_id_forced', 'scheduled_at']), 'start_callback': ('POST', '/callback', [], ['from_number', 'to_number', 'timeout', 'device', 'clir']), 'list_transcriptions': ('GET', '/transcriptions', ['limit_count', 'limit_offset', 'search', 'audio_duration_from', 'audio_duration_to', 'created_from', 'created_to'], []), 'get_transcription': ('GET', '/transcriptions/{callId}', [], []), 'list_groups': ('GET', '/groups', ['limit_count', 'limit_offset'], [])}

class RingoverCreateContactsConfig(BaseModel):
    operation: Literal["create_contacts"] = Field("create_contacts", json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": "Create Contacts", "x-category": "Contacts"})
    contacts: list[dict[str, Any]] = Field(..., min_length=1, max_length=50, description="Contacts with firstname, lastname, company, is_shared and numbers (number and type) as documented by Ringover.")

OPERATIONS["create_contacts"] = ("POST", "/contacts", [], ["contacts"])

CALL_EVENTS = {"call.started": "ringing", "call.answered": "answered", "call.ended": "hangup", "call.missed": "missed", "call.voicemail": "voicemail"}

class RingoverOnCallConfig(WebhookTriggerConfigBase):
    operation: Literal["on_call"] = Field("on_call", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Call Event", "x-category": "Triggers"})
    event_type: Literal["call.started", "call.answered", "call.ended", "call.missed", "call.voicemail"] = Field("call.ended", title="Call Event")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

RingoverConfig = Annotated[Union[RingoverCreateContactsConfig, RingoverGetTeamConfig, RingoverListUsersConfig, RingoverGetUserConfig, RingoverListNumbersConfig, RingoverListCallsConfig, RingoverGetCallConfig, RingoverArchiveCallConfig, RingoverListContactsConfig, RingoverGetContactConfig, RingoverUpdateContactConfig, RingoverDeleteContactConfig, RingoverListTagsConfig, RingoverCreateTagConfig, RingoverListConversationsConfig, RingoverListMessagesConfig, RingoverSendSmsConfig, RingoverStartCallbackConfig, RingoverListTranscriptionsConfig, RingoverGetTranscriptionConfig, RingoverListGroupsConfig, RingoverOnCallConfig], Field(discriminator="operation")]

class RingoverNodeConfig(NodeConfig[RingoverConfig, RingoverAPIKeyCredential]):
    pass

class RingoverNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-ringover"
    connection_evidence = ConnectionEvidence(operation="get_team", noun="Ringover team")

    @classmethod
    def get_config_model(cls):
        return RingoverNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        cred = RingoverAPIKeyCredential.model_validate(credential)
        base = "https://public-api-us.ringover.com/v2" if cred.region == "United States" else "https://public-api.ringover.com/v2"
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, base + path, headers={"Authorization": cred.api_key, "Accept": "application/json"}, params=params, json=body)
        if response.is_error:
            raise ValueError(f"Ringover API {response.status_code}: {response.text}")
        return response.json() if response.content else {}

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, RingoverOnCallConfig):
            payload = (self.node_data.get("config") or {}).get("_triggerPayload")
            return self.resolve_trigger_payload(payload, op.model_dump()) if payload else self.no_event_output("on_call")
        if not self.config.credentials:
            raise ValueError("Connect a Ringover API key")
        method, path, query, body_fields = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        data = await self._request(self.config.credentials.model_dump(), method, path,
            params={k: values[k] for k in query if k in values} or None,
            body={k: values[k] for k in body_fields if k in values} if body_fields else None)
        return {"status": "success", "operation": op.operation, "data": data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = config.get("event_type", "call.ended")
        if event not in CALL_EVENTS:
            raise ValueError("Choose a supported call event")
        result = await cls._request(credential, "POST", "/webhooks", body={"target_url": webhook_url, "events": [event]})
        if not result.get("uuid") or not result.get("signing_key"):
            raise ValueError("Ringover did not return a webhook UUID and signing key")
        return {"external_webhook_id": result["uuid"], "signing_secret": result["signing_key"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if config.get("external_webhook_id"):
            await cls._request(credential, "DELETE", "/webhooks/" + quote(str(config["external_webhook_id"]), safe=""))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": config.get("event_type", "call.ended")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret, url = config.get("signing_secret"), config.get("webhook_url")
        if not secret or not url:
            return False
        headers = {k.lower(): v for k, v in headers.items()}
        if "x-ringover-webhook-signature-v3" in headers:
            timestamp = headers.get("x-ringover-request-signature-v3-timestamp", "")
            if not timestamp:
                return False
            message = b"POST" + url.encode() + body + timestamp.encode()
            expected = base64.b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).decode()
            return hmac.compare_digest(expected, headers["x-ringover-webhook-signature-v3"])
        try:
            claims = jwt.decode(headers.get("x-ringover-webhook-signature", ""), secret, algorithms=["HS512"])
            return claims.get("url") == url and claims.get("payload") == json.loads(body)
        except (jwt.PyJWTError, ValueError):
            return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("resource") == "call" and payload.get("event") == CALL_EVENTS.get(config.get("event_type", "call.ended"))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": "on_call", "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return super().resolve_agent_event(output)
        payload = output.get("data")
        if not isinstance(payload, dict) or payload.get("resource") != "call":
            return super().resolve_agent_event(output)
        data = payload.get("data")
        if not isinstance(data, dict) or not all(data.get(k) is not None for k in ("call_id", "from_number", "to_number")):
            return super().resolve_agent_event(output)
        call_id = str(data["call_id"])
        title = f"Ringover call {payload['event']}: {data['from_number']} → {data['to_number']}"
        return {"text": title + f"\nCall ID: {call_id}. Use get_call with callId={call_id} to inspect the call.\n" + json.dumps(data), "title": title, "conversation_key": call_id}

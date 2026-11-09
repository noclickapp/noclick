"""Vybit Developer API operations using a manually supplied developer API key.

Each operation issues one request against the published v1 API contract.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.vybit.net/v1"


class VybitNotificationsCredential(BaseModel):
    model_config = ConfigDict(title="Vybit Notifications API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.vybit.net",
            "x-credential-instructions": "Generate an API key in your Vybit developer dashboard and paste it here."})
    credential_type: Literal["vybit_notifications_api_key"] = Field("vybit_notifications_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
        description="Your Vybit developer API key. Sent in the X-API-Key header.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if not value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the API key without spaces or a header prefix")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_identifiers(cls, value, info):
        if info.field_name in {"key", "log_key", "vyb_key", "reminder_id"}:
            if not value or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
                raise ValueError("Use the resource key from Vybit")
        return value


class CronEntry(_Config):
    cron: str = Field(..., min_length=1, description="Five-field cron expression")
    timeZone: str = Field(..., min_length=1, title="Time Zone")


class TriggerSettings(_Config):
    crons: list[CronEntry] = Field(default_factory=list)


class Geofence(_Config):
    lat: float
    lon: float
    radius: float
    radiusUnits: Literal["meters", "kilometers", "miles"]
    type: Literal["enter", "exit"]
    timeThrottle: str = "0"
    subscribable: Literal["yes", "no"] = "yes"


class VybitGetProfileConfig(_Config):
    operation: Literal['get_profile'] = Field('get_profile', title='Get User Profile')


class VybitGetMeterConfig(_Config):
    operation: Literal['get_meter'] = Field('get_meter', title='Get Usage Metrics')


class VybitListVybitsConfig(_Config):
    operation: Literal['list_vybits'] = Field('list_vybits', title='List Vybits')
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(30, ge=1, le=100, strict=True)
    search: str | None = Field(None, min_length=1, max_length=255)


class VybitGetVybitConfig(_Config):
    operation: Literal['get_vybit'] = Field('get_vybit', title='Get Vybit')
    key: str = Field(..., min_length=1)


class VybitUpdateVybitPartialConfig(_Config):
    operation: Literal['update_vybit_partial'] = Field('update_vybit_partial', title='Update Vybit (Partial)')
    key: str = Field(..., min_length=1)
    name: str | None = Field(None, max_length=255)
    description: str | None = Field(None)
    sound_key: str | None = Field(None)
    trigger_type: Literal['webhook', 'schedule', 'geofence', 'integration', 'reminders'] | None = Field(None)
    trigger_settings: TriggerSettings | None = Field(None, description='Configuration for scheduled triggers. The crons array replaces the\nexisting array entirely — to remove a cron entry, send the array without it.\nRemoved entries have their scheduled jobs automatically deleted.\n`reminders` is managed only via the Reminders endpoints and is ignored here.\n')
    access: Literal['public', 'private', 'unlisted'] | None = Field(None)
    status: Literal['on', 'off'] | None = Field(None, description='Vybit status (on = active, off = disabled)')
    message: str | None = Field(None, max_length=1024, description='Default message displayed with notifications (max 1024 characters)')
    log: str | None = Field(None, max_length=10000, description="Plain-text default log saved with each notification (max 10,000 characters).\nWhen sent it is escaped, its line breaks are kept, and its http(s) URLs are\nlinked. A trigger's own `log` replaces it.\n")
    image_url: str | None = Field(None, pattern='\\.(jpe?g|png|gif)$', description='Default image URL for notifications. Must link to a JPG, PNG, or GIF image.', json_schema_extra={"format": "uri"})
    link_url: str | None = Field(None, json_schema_extra={"format": "uri"})
    geofence: dict[str, Any] | None = Field(None)
    send_permissions: Literal['owner_subs', 'subs_owner', 'subs_group'] | None = Field(None)


class VybitDeleteVybitConfig(_Config):
    operation: Literal['delete_vybit'] = Field('delete_vybit', title='Delete Vybit')
    key: str = Field(..., min_length=1)


class VybitTriggerVybitConfig(_Config):
    operation: Literal['trigger_vybit'] = Field('trigger_vybit', title='Trigger Vybit Notification')
    key: str = Field(..., min_length=1)
    message: str | None = Field(None, description='Custom notification message')
    image_url: str | None = Field(None, pattern='\\.(jpe?g|png|gif)$', description='Custom image URL. Must link to a JPG, PNG, or GIF image; non-image URLs are silently ignored.', json_schema_extra={"format": "uri"})
    link_url: str | None = Field(None, description='Custom link URL', json_schema_extra={"format": "uri"})
    log: str | None = Field(None, description="Log entry saved with this notification; replaces the vybit's default `log`.\nA log over 10,000 characters is truncated to 10,000 (ending in an ellipsis)\nrather than refused.\n")
    run_once: bool | None = Field(None, description='If true, the vybit is automatically disabled (status set to "off") after this trigger fires. For schedule trigger types, the scheduled job is also paused.')


class VybitCreateReminderConfig(_Config):
    operation: Literal['create_reminder'] = Field('create_reminder', title='Create Reminder')
    key: str = Field(..., min_length=1)
    cron: str = Field(..., pattern='^\\S+\\s+\\S+\\s+\\d{1,2}\\s+\\d{1,2}\\s+\\*$', min_length=1, description='Cron expression naming the one date the reminder fires.\nFormat: minute hour day month dayOfWeek, with a numeric day and month\nand `*` for dayOfWeek.\n')
    time_zone: str = Field('UTC', description='IANA timezone identifier')
    year: int | None = Field(None, strict=True, description='Year for the reminder (defaults to current year). Used for one-time reminders — expired reminders are automatically garbage-collected.')
    message: str | None = Field(None, max_length=1024, description='Notification message for this reminder (max 1024 characters)')
    image_url: str | None = Field(None, max_length=512, pattern='\\.(jpe?g|png|gif)$', description="Image URL for this reminder's notification (max 512 characters). Must link to a JPG, PNG, or GIF image. URLs without a protocol will have https:// prepended.", json_schema_extra={"format": "uri"})
    link_url: str | None = Field(None, max_length=512, description="Link URL for this reminder's notification (max 512 characters). URLs without a protocol will have https:// prepended.", json_schema_extra={"format": "uri"})
    log: str | None = Field(None, max_length=10000, description="Log content for this reminder's notification (max 10,000 characters)")


class VybitListRemindersConfig(_Config):
    operation: Literal['list_reminders'] = Field('list_reminders', title='List Reminders')
    key: str = Field(..., min_length=1)


class VybitUpdateReminderConfig(_Config):
    operation: Literal['update_reminder'] = Field('update_reminder', title='Update Reminder')
    key: str = Field(..., min_length=1)
    reminder_id: str = Field(..., min_length=1)
    cron: str | None = Field(None, pattern='^\\S+\\s+\\S+\\s+\\d{1,2}\\s+\\d{1,2}\\s+\\*$', description='Updated cron expression naming one date (minute hour day month dayOfWeek, with a numeric day and month and * for dayOfWeek)')
    time_zone: str | None = Field(None, description='Updated IANA timezone')
    message: str | None = Field(None, max_length=1024, description='Updated notification message (max 1024 characters)')
    image_url: str | None = Field(None, max_length=512, pattern='\\.(jpe?g|png|gif)$', description='Updated image URL (max 512 characters). Must link to a JPG, PNG, or GIF image. URLs without a protocol will have https:// prepended.', json_schema_extra={"format": "uri"})
    link_url: str | None = Field(None, max_length=512, description='Updated link URL (max 512 characters). URLs without a protocol will have https:// prepended.', json_schema_extra={"format": "uri"})
    log: str | None = Field(None, max_length=10000, description='Updated log content (max 10,000 characters)')


class VybitDeleteReminderConfig(_Config):
    operation: Literal['delete_reminder'] = Field('delete_reminder', title='Delete Reminder')
    key: str = Field(..., min_length=1)
    reminder_id: str = Field(..., min_length=1)


class VybitCreateVybitConfig(_Config):
    operation: Literal['create_vybit'] = Field('create_vybit', title='Create Vybit')
    name: str = Field(..., max_length=64, min_length=1, description='Vybit display name')
    description: str = Field('', max_length=512, description='Detailed vybit description')
    sound_key: str | None = Field(None, description='Key of the sound to play (must be an available sound from /sounds endpoint)')
    status: Literal['on', 'off'] = Field('on', description='Vybit status (on = active, off = disabled)')
    trigger_type: Literal['webhook', 'schedule', 'geofence', 'integration', 'reminders'] = Field('webhook', description='How this vybit is triggered')
    trigger_settings: TriggerSettings | None = Field(None, description='Configuration for scheduled triggers.\nRequired when triggerType is "schedule", null otherwise.\nFor triggerType "reminders", reminders are managed only via the Reminders endpoints; any sent here are ignored.\n')
    access: Literal['public', 'private', 'unlisted'] = Field('private', description='Vybit visibility and access control')
    message: str | None = Field(None, max_length=1024, description='Default message displayed with notifications (max 1024 characters)')
    log: str | None = Field(None, max_length=10000, description="Plain-text default log saved with each notification (max 10,000 characters).\nWhen sent it is escaped, its line breaks are kept, and its http(s) URLs are\nlinked. A trigger's own `log` replaces it.\n")
    image_url: str | None = Field(None, pattern='\\.(jpe?g|png|gif)$', description='Default image URL for notifications. Must link to a JPG, PNG, or GIF image.', json_schema_extra={"format": "uri"})
    link_url: str | None = Field(None, description='Default URL to open when notification is tapped', json_schema_extra={"format": "uri"})
    geofence: Geofence | None = Field(None, description='Geofence configuration. Required when triggerType is "geofence", null otherwise.\n')
    send_permissions: Literal['owner_subs', 'subs_owner', 'subs_group'] = Field('owner_subs', description='Who can trigger and receive notifications:\n- owner_subs: owner triggers → subscribers receive (one-way)\n- subs_owner: owner ↔ subscribers (two-way between owner and each subscriber)\n- subs_group: subscribers trigger → all subscribers receive (group broadcast)\n')

    @model_validator(mode="after")
    def required_settings(self):
        if self.trigger_type == "schedule" and self.trigger_settings is None:
            raise ValueError("Scheduled vybits require trigger settings")
        if self.trigger_type == "geofence" and self.geofence is None:
            raise ValueError("Geofenced vybits require geofence settings")
        return self


class VybitListPublicVybitsConfig(_Config):
    operation: Literal['list_public_vybits'] = Field('list_public_vybits', title='List Public Vybits')
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(30, ge=1, le=100, strict=True)
    search: str | None = Field(None, min_length=1, max_length=255)


class VybitGetPublicVybitConfig(_Config):
    operation: Literal['get_public_vybit'] = Field('get_public_vybit', title='Get Public Vybit by Subscription Key')
    key: str = Field(..., min_length=1)


class VybitCreateSubscriptionConfig(_Config):
    operation: Literal['create_subscription'] = Field('create_subscription', title='Subscribe to Vybit')
    key: str = Field(..., min_length=1)


class VybitListSubscriptionsConfig(_Config):
    operation: Literal['list_subscriptions'] = Field('list_subscriptions', title='List Vybit Subscriptions')
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(30, ge=1, le=100, strict=True)
    search: str | None = Field(None, min_length=1, max_length=255)


class VybitGetSubscriptionConfig(_Config):
    operation: Literal['get_subscription'] = Field('get_subscription', title='Get Subscription Following')
    key: str = Field(..., min_length=1)


class VybitDeleteSubscriptionConfig(_Config):
    operation: Literal['delete_subscription'] = Field('delete_subscription', title='Unsubscribe from Vybit')
    key: str = Field(..., min_length=1)


class VybitSendToOwnerConfig(_Config):
    operation: Literal['send_to_owner'] = Field('send_to_owner', title='Send Notification to Owner')
    key: str = Field(..., min_length=1)
    message: str | None = Field(None, description='Notification message')
    image_url: str | None = Field(None, pattern='\\.(jpe?g|png|gif)$', description='Custom image URL. Must link to a JPG, PNG, or GIF image.', json_schema_extra={"format": "uri"})
    link_url: str | None = Field(None, description='Custom link URL', json_schema_extra={"format": "uri"})


class VybitSendToGroupConfig(_Config):
    operation: Literal['send_to_group'] = Field('send_to_group', title='Send Notification to Group')
    key: str = Field(..., min_length=1)
    message: str | None = Field(None, description='Notification message')
    image_url: str | None = Field(None, pattern='\\.(jpe?g|png|gif)$', description='Custom image URL. Must link to a JPG, PNG, or GIF image.', json_schema_extra={"format": "uri"})
    link_url: str | None = Field(None, description='Custom link URL', json_schema_extra={"format": "uri"})


class VybitSearchSoundsConfig(_Config):
    operation: Literal['search_sounds'] = Field('search_sounds', title='Search Sounds')
    search: str | None = Field(None)
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(30, ge=1, le=100, strict=True)


class VybitGetSoundConfig(_Config):
    operation: Literal['get_sound'] = Field('get_sound', title='Get Sound Details')
    key: str = Field(..., min_length=1)


class VybitListLogsConfig(_Config):
    operation: Literal['list_logs'] = Field('list_logs', title='List All Logs')
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(30, ge=1, le=100, strict=True)
    search: str | None = Field(None, min_length=1, max_length=255)


class VybitGetLogConfig(_Config):
    operation: Literal['get_log'] = Field('get_log', title='Get Log Entry')
    log_key: str = Field(..., min_length=1)


class VybitListVybitLogsConfig(_Config):
    operation: Literal['list_vybit_logs'] = Field('list_vybit_logs', title='List Logs for Owned Vybit')
    vyb_key: str = Field(..., min_length=1)
    offset: int = Field(0, ge=0, strict=True)
    limit: int = Field(30, ge=1, le=100, strict=True)
    search: str | None = Field(None)


VybitOperation = Annotated[Union[
    VybitGetProfileConfig,
    VybitGetMeterConfig,
    VybitListVybitsConfig,
    VybitGetVybitConfig,
    VybitUpdateVybitPartialConfig,
    VybitDeleteVybitConfig,
    VybitTriggerVybitConfig,
    VybitCreateReminderConfig,
    VybitListRemindersConfig,
    VybitUpdateReminderConfig,
    VybitDeleteReminderConfig,
    VybitCreateVybitConfig,
    VybitListPublicVybitsConfig,
    VybitGetPublicVybitConfig,
    VybitCreateSubscriptionConfig,
    VybitListSubscriptionsConfig,
    VybitGetSubscriptionConfig,
    VybitDeleteSubscriptionConfig,
    VybitSendToOwnerConfig,
    VybitSendToGroupConfig,
    VybitSearchSoundsConfig,
    VybitGetSoundConfig,
    VybitListLogsConfig,
    VybitGetLogConfig,
    VybitListVybitLogsConfig
], Field(discriminator="operation")]


class VybitNotificationsConfig(NodeConfig[VybitOperation, VybitNotificationsCredential]):
    pass


ROUTES = {'get_profile': ('GET', '/profile', {}, []),
 'get_meter': ('GET', '/meter', {}, []),
 'list_vybits': ('GET', '/vybits', {}, ['offset', 'limit', 'search']),
 'get_vybit': ('GET', '/vybit/{key}', {'key': 'key'}, []),
 'update_vybit_partial': ('PATCH', '/vybit/{key}', {'key': 'key'}, []),
 'delete_vybit': ('DELETE', '/vybit/{key}', {'key': 'key'}, []),
 'trigger_vybit': ('POST', '/vybit/{key}/trigger', {'key': 'key'}, []),
 'create_reminder': ('POST', '/vybit/{key}/reminders', {'key': 'key'}, []),
 'list_reminders': ('GET', '/vybit/{key}/reminders', {'key': 'key'}, []),
 'update_reminder': ('PATCH',
                     '/vybit/{key}/reminders/{reminderId}',
                     {'key': 'key', 'reminder_id': 'reminderId'},
                     []),
 'delete_reminder': ('DELETE',
                     '/vybit/{key}/reminders/{reminderId}',
                     {'key': 'key', 'reminder_id': 'reminderId'},
                     []),
 'create_vybit': ('POST', '/vybit', {}, []),
 'list_public_vybits': ('GET', '/subscriptions/public', {}, ['offset', 'limit', 'search']),
 'get_public_vybit': ('GET', '/subscription/{key}', {'key': 'key'}, []),
 'create_subscription': ('POST', '/subscription/{key}', {'key': 'key'}, []),
 'list_subscriptions': ('GET', '/subscriptions/following', {}, ['offset', 'limit', 'search']),
 'get_subscription': ('GET', '/subscription/following/{key}', {'key': 'key'}, []),
 'delete_subscription': ('DELETE', '/subscription/following/{key}', {'key': 'key'}, []),
 'send_to_owner': ('POST', '/subscription/following/{key}/send-to-owner', {'key': 'key'}, []),
 'send_to_group': ('POST', '/subscription/following/{key}/send-to-group', {'key': 'key'}, []),
 'search_sounds': ('GET', '/sounds', {}, ['search', 'offset', 'limit']),
 'get_sound': ('GET', '/sound/{key}', {'key': 'key'}, []),
 'list_logs': ('GET', '/logs', {}, ['offset', 'limit', 'search']),
 'get_log': ('GET', '/log/{logKey}', {'log_key': 'logKey'}, []),
 'list_vybit_logs': ('GET',
                     '/logs/vybit/{vybKey}',
                     {'vyb_key': 'vybKey'},
                     ['offset', 'limit', 'search'])}
BODY_FIELDS = {'get_profile': {},
 'get_meter': {},
 'list_vybits': {},
 'get_vybit': {},
 'update_vybit_partial': {'name': 'name',
                          'description': 'description',
                          'sound_key': 'soundKey',
                          'trigger_type': 'triggerType',
                          'trigger_settings': 'triggerSettings',
                          'access': 'access',
                          'status': 'status',
                          'message': 'message',
                          'log': 'log',
                          'image_url': 'imageUrl',
                          'link_url': 'linkUrl',
                          'geofence': 'geofence',
                          'send_permissions': 'sendPermissions'},
 'delete_vybit': {},
 'trigger_vybit': {'message': 'message',
                   'image_url': 'imageUrl',
                   'link_url': 'linkUrl',
                   'log': 'log',
                   'run_once': 'runOnce'},
 'create_reminder': {'cron': 'cron',
                     'time_zone': 'timeZone',
                     'year': 'year',
                     'message': 'message',
                     'image_url': 'imageUrl',
                     'link_url': 'linkUrl',
                     'log': 'log'},
 'list_reminders': {},
 'update_reminder': {'cron': 'cron',
                     'time_zone': 'timeZone',
                     'message': 'message',
                     'image_url': 'imageUrl',
                     'link_url': 'linkUrl',
                     'log': 'log'},
 'delete_reminder': {},
 'create_vybit': {'name': 'name',
                  'description': 'description',
                  'sound_key': 'soundKey',
                  'status': 'status',
                  'trigger_type': 'triggerType',
                  'trigger_settings': 'triggerSettings',
                  'access': 'access',
                  'message': 'message',
                  'log': 'log',
                  'image_url': 'imageUrl',
                  'link_url': 'linkUrl',
                  'geofence': 'geofence',
                  'send_permissions': 'sendPermissions'},
 'list_public_vybits': {},
 'get_public_vybit': {},
 'create_subscription': {},
 'list_subscriptions': {},
 'get_subscription': {},
 'delete_subscription': {},
 'send_to_owner': {'message': 'message', 'image_url': 'imageUrl', 'link_url': 'linkUrl'},
 'send_to_group': {'message': 'message', 'image_url': 'imageUrl', 'link_url': 'linkUrl'},
 'search_sounds': {},
 'get_sound': {},
 'list_logs': {},
 'get_log': {},
 'list_vybit_logs': {}}
NULLABLE_FIELDS = {'get_profile': [],
 'get_meter': [],
 'list_vybits': [],
 'get_vybit': [],
 'update_vybit_partial': ['trigger_settings',
                          'message',
                          'log',
                          'image_url',
                          'link_url',
                          'geofence'],
 'delete_vybit': [],
 'trigger_vybit': [],
 'create_reminder': ['message', 'image_url', 'link_url', 'log'],
 'list_reminders': [],
 'update_reminder': ['message', 'image_url', 'link_url', 'log'],
 'delete_reminder': [],
 'create_vybit': ['trigger_settings', 'message', 'log', 'image_url', 'link_url', 'geofence'],
 'list_public_vybits': [],
 'get_public_vybit': [],
 'create_subscription': [],
 'list_subscriptions': [],
 'get_subscription': [],
 'delete_subscription': [],
 'send_to_owner': [],
 'send_to_group': [],
 'search_sounds': [],
 'get_sound': [],
 'list_logs': [],
 'get_log': [],
 'list_vybit_logs': []}


class VybitNotificationsNode(WorkflowNode):
    integration_type = "automation-vybit-notifications"
    connection_evidence = ConnectionEvidence(noun="Vybit account", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return VybitNotificationsConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Vybit Notifications API key")
        config = self.config.config
        method, path, path_fields, query_fields = ROUTES[config.operation]
        for field, placeholder in path_fields.items():
            path = path.replace("{" + placeholder + "}", quote(getattr(config, field), safe=""))
        values = config.model_dump()
        params = {field: values[field] for field in query_fields if values[field] is not None}
        payload = {wire: values[field] for field, wire in BODY_FIELDS[config.operation].items()
            if values[field] is not None or (field in config.model_fields_set and field in NULLABLE_FIELDS[config.operation])}
        kwargs = {"params": params} if method == "GET" else {"json": payload} if method in {"POST", "PATCH"} else {}
        api_key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"X-API-Key": api_key, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection wording for the shared connection-evidence seam.
            error = response.text.replace(api_key, "[redacted]")[:4000]
            raise ValueError(f"Vybit HTTP {response.status_code}: {error}")
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ValueError("Vybit returned a non-JSON response")
        result = response.json()
        if not isinstance(result, (dict, list)):
            raise ValueError("Vybit returned an unexpected response shape")
        if isinstance(result, dict) and (result.get("error") or result.get("result") == 0 and not result.get("warn")):
            raise ValueError("Vybit did not confirm the operation: " + str(result).replace(api_key, "[redacted]")[:4000])
        if config.operation == "get_profile" and not (isinstance(result, dict) and result.get("key") and (result.get("name") or result.get("email"))):
            raise ValueError("Vybit returned an incomplete account profile")
        # Keep provider fields, including a 201 trigger warning, without claiming delivery.
        output = {"data": result}
        if isinstance(result, dict):
            output.update({key: value for key, value in result.items() if key in {"name", "email"}})
        if query_fields:
            if not isinstance(result, list):
                raise ValueError("Vybit returned an unexpected collection shape")
            output["next_offset"] = config.offset + len(result) if len(result) == config.limit else None
        await self.emit(output)
        return output

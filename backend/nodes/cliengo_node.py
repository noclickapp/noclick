"""Cliengo Public API 1.0: contacts, inbox conversations and CRM lookups.

Contract: https://developers.cliengo.com/openapi.json. Each operation sends
one documented request. Writes are never retried automatically.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, AwareDatetime
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class CliengoAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Cliengo API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dash.cliengo.com/integrations/connect_api",
            "x-credential-instructions": "In Cliengo, open Integrations → API, generate a token with the permissions your operations need, and paste it here. Contacts need clients_read/clients_write; conversations, tags and phases need conversations_read/conversations_write; channels need websites_read; users need users_read. Account reads prove the connection. Production tokens use connect.cliengo.com; sk_test_ tokens use connect.stagecliengo.com."})
    credential_type: Literal["cliengo_api_token"] = Field("cliengo_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token alone, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_path_ids(cls, value, info):
        if info.field_name in {"contact_id", "conversation_id", "channel_id", "phase_id", "sender_id"} and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
                raise ValueError("Use a single Cliengo resource ID")
        return value


class CliengoSearchContactsConfig(_Input):
    operation: Literal['search_contacts'] = Field('search_contacts', json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, description='Búsqueda fuzzy en nombre, email y teléfono', min_length=1, max_length=1000)
    email: str | None = Field(None, description='Filtrar por email (búsqueda parcial)', min_length=1, max_length=1000)
    name: str | None = Field(None, description='Filtrar por nombre (búsqueda parcial)', min_length=1, max_length=1000)
    phone: str | None = Field(None, description='Filtrar por teléfono (búsqueda parcial)', min_length=1, max_length=1000)
    status: Literal['new', 'active', 'client', 'long_term'] | None = Field(None, description='Filtrar por estado del contacto')
    sub_status: str | None = Field(None, description='Filtrar por sub-estado', min_length=1, max_length=1000)
    website_id: str | None = Field(None, description='Filtrar por canal (IDs separados por coma)', min_length=1, max_length=1000)
    assigned_to: str | None = Field(None, description='Filtrar por agente asignado (IDs separados por coma, o UNASSIGNED)', min_length=1, max_length=1000)
    entry_method: str | None = Field(None, description='Filtrar por método de entrada (WEB, WHATSAPP, FACEBOOK, etc.)', min_length=1, max_length=1000)
    conversation_tags: str | None = Field(None, description='Filtrar por tags de conversación (separados por coma)', min_length=1, max_length=1000)
    rating: str | None = Field(None, description='Filtrar por calificación (valores separados por coma)', min_length=1, max_length=1000)
    date_from: AwareDatetime | None = Field(None, description='Contactos creados después de esta fecha (ISO 8601)')
    date_to: AwareDatetime | None = Field(None, description='Contactos creados antes de esta fecha (ISO 8601)')
    last_update_date_from: AwareDatetime | None = Field(None, description='Contactos actualizados después de esta fecha (ISO 8601)')
    last_update_date_to: AwareDatetime | None = Field(None, description='Contactos actualizados antes de esta fecha (ISO 8601)')
    order_by: str = Field('_id', description='Campo para ordenar (ej: creationDate, name, email)', max_length=1000)
    order: Literal['asc', 'desc'] = Field('desc', description='Dirección de ordenamiento')
    page: int = Field(1, description='Número de página', ge=1)
    limit: int = Field(20, description='Resultados por página', ge=1, le=100)

class CliengoCreateContactConfig(_Input):
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={"ui:hidden": True})
    website_id: str = Field(..., description='ID del canal donde se origina el contacto', min_length=1, max_length=1000)
    name: str = Field(..., min_length=1, max_length=1000)
    email: str | None = Field(None, min_length=1, max_length=1000)
    phone: str | None = Field(None, min_length=1, max_length=1000)
    international_phone_number: str | None = Field(None, min_length=1, max_length=1000)
    message: str | None = Field(None, min_length=1, max_length=20000)
    status: Literal['new', 'active', 'client', 'long_term'] | None = Field(None)
    entry_method: str | None = Field(None, min_length=1, max_length=1000)
    assigned_to: str | None = Field(None, description='ID del agente a asignar', min_length=1, max_length=1000)
    note: str | None = Field(None, description='Nota inicial del contacto', min_length=1, max_length=20000)
    custom_fields: dict[str, Any] | None = Field(None, description='Campos personalizados (key-value)')

class CliengoGetContactConfig(_Input):
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=1000)

class CliengoUpdateContactConfig(_Input):
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=1000)
    name: str | None = Field(None, min_length=1, max_length=1000)
    email: str | None = Field(None, min_length=1, max_length=1000)
    phone: str | None = Field(None, min_length=1, max_length=1000)
    status: str | None = Field(None, min_length=1, max_length=1000)
    assigned_to: str | None = Field(None, min_length=1, max_length=1000)

class CliengoDeleteContactConfig(_Input):
    operation: Literal['delete_contact'] = Field('delete_contact', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=1000)

class CliengoListContactNotesConfig(_Input):
    operation: Literal['list_contact_notes'] = Field('list_contact_notes', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=1000)

class CliengoCreateContactNoteConfig(_Input):
    operation: Literal['create_contact_note'] = Field('create_contact_note', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=1000)
    message: str = Field(..., min_length=1, max_length=20000)

class CliengoAddContactTagConfig(_Input):
    operation: Literal['add_contact_tag'] = Field('add_contact_tag', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=1000)
    tag: str = Field(..., min_length=1, max_length=1000)

class CliengoGetContactHistoryConfig(_Input):
    operation: Literal['get_contact_history'] = Field('get_contact_history', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, max_length=1000)

class CliengoListConversationsConfig(_Input):
    operation: Literal['list_conversations'] = Field('list_conversations', json_schema_extra={"ui:hidden": True})
    status: Literal['opened', 'closed', 'inactive'] | None = Field(None, description='Estado de la conversación')
    tags: str | None = Field(None, description='Filtrar por tags. Uno o varios valores en un **único** parámetro, separados por coma (ej. `?tags=urgente,vip`), no como parámetros repetidos.', min_length=1, max_length=1000)
    from_date: AwareDatetime | None = Field(None, description='Fecha de inicio (ISO 8601)')
    to_date: AwareDatetime | None = Field(None, description='Fecha de fin (ISO 8601)')
    channel: str | None = Field(None, description='Filtrar por canal. Uno o varios valores (`WEB`, `WHATSAPP`, `FACEBOOK`, `INSTAGRAM`) en un **único** parámetro, separados por coma (ej. `?channel=WEB,WHATSAPP`), no como parámetros repetidos.', min_length=1, max_length=1000)
    phase: str | None = Field(None, description='ID de la fase (etapa de inbox)', min_length=1, max_length=1000)
    agent: str | None = Field(None, description='ID del agente que **intervino** la conversación (último operador que envió un mensaje). Devuelve las conversaciones intervenidas por ese agente. Usá `robot` para traer solo las atendidas por el bot (sin intervención humana).', min_length=1, max_length=1000)
    pre_assigned: str | None = Field(None, description='ID del agente **asignado** (pre-asignación automática). Devuelve las conversaciones asignadas a ese agente.', min_length=1, max_length=1000)
    condition: str | None = Field(None, description='Filtra por estado de intervención. Uno o varios valores en un **único** parámetro, separados por coma (ej. `?condition=intervened,lead`): `intervened` (intervenidas por un humano), `not_intervened` (atendidas solo por el bot), `lead` (marcadas como lead).', min_length=1, max_length=1000)
    utm_source: str | None = Field(None, description='Filtrar por fuente de campaña (UTM source). Ej. `google`, `facebook`.', min_length=1, max_length=1000)
    utm_medium: str | None = Field(None, description='Filtrar por medio de campaña (UTM medium). Ej. `cpc`, `organic`.', min_length=1, max_length=1000)
    utm_campaign: str | None = Field(None, description='Filtrar por nombre de campaña (UTM campaign).', min_length=1, max_length=1000)
    search: str | None = Field(None, description='Búsqueda de texto libre', min_length=1, max_length=1000)
    limit: int = Field(20, description='Resultados por página', ge=1, le=100)
    offset: int | None = Field(None, description='Use an offset instead of a page number. When set, page is not sent.', ge=0)
    page: int = Field(1, description='Número de página', ge=1)
    sort: str | None = Field(None, description='Campo y orden de ordenamiento (ej: createdAt:desc)', min_length=1, max_length=1000)

class CliengoGetConversationConfig(_Input):
    operation: Literal['get_conversation'] = Field('get_conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000)

class CliengoListConversationMessagesConfig(_Input):
    operation: Literal['list_conversation_messages'] = Field('list_conversation_messages', json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000)
    include_commands: bool = Field(False, description='Si es `true`, incluye los mensajes de tipo **comando** (eventos internos del sistema: asignaciones, cambios de fase, notas de bot, etc.) además de los mensajes de conversación. Por defecto (`false`) solo se devuelven los mensajes de la charla.')

class CliengoSendConversationMessageConfig(_Input):
    operation: Literal['send_conversation_message'] = Field('send_conversation_message', json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000)
    body: str | None = Field(None, min_length=1, max_length=20000)
    from_type: Literal['user', 'robot', 'visitor'] = Field(...)
    sender_id: str = Field(..., description='ID del remitente', min_length=1, max_length=1000)
    message_type: Literal['image', 'text/plain', 'command', 'note'] = Field(...)
    message: dict[str, Any] | None = Field(None, description='Para mensajes multimedia')

class CliengoAssignConversationConfig(_Input):
    operation: Literal['assign_conversation'] = Field('assign_conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000)
    assigned_to: str = Field(..., description='ID del operador', min_length=1, max_length=1000)

class CliengoCloseConversationConfig(_Input):
    operation: Literal['close_conversation'] = Field('close_conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000)
    is_lead: bool = Field(..., description='Si la conversación resultó en un lead')

class CliengoOpenConversationConfig(_Input):
    operation: Literal['open_conversation'] = Field('open_conversation', json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000)

class CliengoListTagsConfig(_Input):
    operation: Literal['list_tags'] = Field('list_tags', json_schema_extra={"ui:hidden": True})

class CliengoCreateTagConfig(_Input):
    operation: Literal['create_tag'] = Field('create_tag', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    color: str | None = Field(None, min_length=1, max_length=1000)

class CliengoListPhasesConfig(_Input):
    operation: Literal['list_phases'] = Field('list_phases', json_schema_extra={"ui:hidden": True})

class CliengoAssignConversationPhaseConfig(_Input):
    operation: Literal['assign_conversation_phase'] = Field('assign_conversation_phase', json_schema_extra={"ui:hidden": True})
    conversation_id: str = Field(..., min_length=1, max_length=1000)
    phase_id: str = Field(..., min_length=1, max_length=1000)

class CliengoGetAccountConfig(_Input):
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={"ui:hidden": True})

class CliengoListChannelsConfig(_Input):
    operation: Literal['list_channels'] = Field('list_channels', json_schema_extra={"ui:hidden": True})

class CliengoListUsersConfig(_Input):
    operation: Literal['list_users'] = Field('list_users', json_schema_extra={"ui:hidden": True})
    limit: int = Field(20, description='Resultados por página', ge=1, le=100)
    offset: int = Field(0, description='Offset de paginación', ge=0)

class CliengoListWhatsappTemplatesConfig(_Input):
    operation: Literal['list_whatsapp_templates'] = Field('list_whatsapp_templates', json_schema_extra={"ui:hidden": True})
    channel_id: str = Field(..., description='ID del canal de WhatsApp (websiteId)', min_length=1, max_length=1000)

class CliengoListTeamsConfig(_Input):
    operation: Literal['list_teams'] = Field('list_teams', json_schema_extra={"ui:hidden": True})


CliengoConfig = Annotated[Union[
    CliengoSearchContactsConfig,
    CliengoCreateContactConfig,
    CliengoGetContactConfig,
    CliengoUpdateContactConfig,
    CliengoDeleteContactConfig,
    CliengoListContactNotesConfig,
    CliengoCreateContactNoteConfig,
    CliengoAddContactTagConfig,
    CliengoGetContactHistoryConfig,
    CliengoListConversationsConfig,
    CliengoGetConversationConfig,
    CliengoListConversationMessagesConfig,
    CliengoSendConversationMessageConfig,
    CliengoAssignConversationConfig,
    CliengoCloseConversationConfig,
    CliengoOpenConversationConfig,
    CliengoListTagsConfig,
    CliengoCreateTagConfig,
    CliengoListPhasesConfig,
    CliengoAssignConversationPhaseConfig,
    CliengoGetAccountConfig,
    CliengoListChannelsConfig,
    CliengoListUsersConfig,
    CliengoListWhatsappTemplatesConfig,
    CliengoListTeamsConfig
], Field(discriminator="operation")]


class CliengoFullConfig(NodeConfig[CliengoConfig, CliengoAPITokenCredential]):
    pass


OPERATIONS = {'search_contacts': {'method': 'GET',
                     'path': '/v1/contacts',
                     'path_fields': {},
                     'query_fields': {'search': 'search',
                                      'email': 'email',
                                      'name': 'name',
                                      'phone': 'phone',
                                      'status': 'status',
                                      'sub_status': 'subStatus',
                                      'website_id': 'websiteId',
                                      'assigned_to': 'assignedTo',
                                      'entry_method': 'entryMethod',
                                      'conversation_tags': 'conversationTags',
                                      'rating': 'rating',
                                      'date_from': 'dateFrom',
                                      'date_to': 'dateTo',
                                      'last_update_date_from': 'lastUpdateDateFrom',
                                      'last_update_date_to': 'lastUpdateDateTo',
                                      'order_by': 'orderBy',
                                      'order': 'order',
                                      'page': 'page',
                                      'limit': 'limit'},
                     'body_fields': {},
                     'has_body': False,
                     'contract_operation': 'searchContacts'},
 'create_contact': {'method': 'POST',
                    'path': '/v1/contacts',
                    'path_fields': {},
                    'query_fields': {},
                    'body_fields': {'website_id': 'websiteId',
                                    'name': 'name',
                                    'email': 'email',
                                    'phone': 'phone',
                                    'international_phone_number': 'internationalPhoneNumber',
                                    'message': 'message',
                                    'status': 'status',
                                    'entry_method': 'entryMethod',
                                    'assigned_to': 'assignedTo',
                                    'note': 'note',
                                    'custom_fields': 'customFields'},
                    'has_body': True,
                    'contract_operation': 'createContact'},
 'get_contact': {'method': 'GET',
                 'path': '/v1/contacts/{contactId}',
                 'path_fields': {'contact_id': 'contactId'},
                 'query_fields': {},
                 'body_fields': {},
                 'has_body': False,
                 'contract_operation': 'getContact'},
 'update_contact': {'method': 'PATCH',
                    'path': '/v1/contacts/{contactId}',
                    'path_fields': {'contact_id': 'contactId'},
                    'query_fields': {},
                    'body_fields': {'name': 'name',
                                    'email': 'email',
                                    'phone': 'phone',
                                    'status': 'status',
                                    'assigned_to': 'assignedTo'},
                    'has_body': True,
                    'contract_operation': 'patchContact'},
 'delete_contact': {'method': 'DELETE',
                    'path': '/v1/contacts/{contactId}',
                    'path_fields': {'contact_id': 'contactId'},
                    'query_fields': {},
                    'body_fields': {},
                    'has_body': False,
                    'contract_operation': 'deleteContact'},
 'list_contact_notes': {'method': 'GET',
                        'path': '/v1/contacts/{contactId}/notes',
                        'path_fields': {'contact_id': 'contactId'},
                        'query_fields': {},
                        'body_fields': {},
                        'has_body': False,
                        'contract_operation': 'listContactNotes'},
 'create_contact_note': {'method': 'POST',
                         'path': '/v1/contacts/{contactId}/notes',
                         'path_fields': {'contact_id': 'contactId'},
                         'query_fields': {},
                         'body_fields': {'message': 'message'},
                         'has_body': True,
                         'contract_operation': 'createContactNote'},
 'add_contact_tag': {'method': 'POST',
                     'path': '/v1/contacts/{contactId}/tags',
                     'path_fields': {'contact_id': 'contactId'},
                     'query_fields': {},
                     'body_fields': {'tag': 'tag'},
                     'has_body': True,
                     'contract_operation': 'addContactTag'},
 'get_contact_history': {'method': 'GET',
                         'path': '/v1/contacts/{contactId}/history',
                         'path_fields': {'contact_id': 'contactId'},
                         'query_fields': {},
                         'body_fields': {},
                         'has_body': False,
                         'contract_operation': 'getContactHistory'},
 'list_conversations': {'method': 'GET',
                        'path': '/v1/conversations',
                        'path_fields': {},
                        'query_fields': {'status': 'status',
                                         'tags': 'tags',
                                         'from_date': 'fromDate',
                                         'to_date': 'toDate',
                                         'channel': 'channel',
                                         'phase': 'phase',
                                         'agent': 'agent',
                                         'pre_assigned': 'preAssigned',
                                         'condition': 'condition',
                                         'utm_source': 'utmSource',
                                         'utm_medium': 'utmMedium',
                                         'utm_campaign': 'utmCampaign',
                                         'search': 'search',
                                         'limit': 'limit',
                                         'offset': 'offset',
                                         'page': 'page',
                                         'sort': 'sort'},
                        'body_fields': {},
                        'has_body': False,
                        'contract_operation': 'listConversations'},
 'get_conversation': {'method': 'GET',
                      'path': '/v1/conversations/{conversationId}',
                      'path_fields': {'conversation_id': 'conversationId'},
                      'query_fields': {},
                      'body_fields': {},
                      'has_body': False,
                      'contract_operation': 'getConversation'},
 'list_conversation_messages': {'method': 'GET',
                                'path': '/v1/conversations/{conversationId}/messages',
                                'path_fields': {'conversation_id': 'conversationId'},
                                'query_fields': {'include_commands': 'includeCommands'},
                                'body_fields': {},
                                'has_body': False,
                                'contract_operation': 'listConversationMessages'},
 'send_conversation_message': {'method': 'POST',
                               'path': '/v1/conversations/{conversationId}/messages',
                               'path_fields': {'conversation_id': 'conversationId'},
                               'query_fields': {},
                               'body_fields': {'body': 'body',
                                               'from_type': 'fromType',
                                               'sender_id': 'from',
                                               'message_type': 'type',
                                               'message': 'message'},
                               'has_body': True,
                               'contract_operation': 'addConversationMessage'},
 'assign_conversation': {'method': 'POST',
                         'path': '/v1/conversations/{conversationId}/assign',
                         'path_fields': {'conversation_id': 'conversationId'},
                         'query_fields': {},
                         'body_fields': {'assigned_to': 'assignedTo'},
                         'has_body': True,
                         'contract_operation': 'assignConversation'},
 'close_conversation': {'method': 'POST',
                        'path': '/v1/conversations/{conversationId}/close',
                        'path_fields': {'conversation_id': 'conversationId'},
                        'query_fields': {},
                        'body_fields': {'is_lead': 'isLead'},
                        'has_body': True,
                        'contract_operation': 'closeConversation'},
 'open_conversation': {'method': 'POST',
                       'path': '/v1/conversations/{conversationId}/open',
                       'path_fields': {'conversation_id': 'conversationId'},
                       'query_fields': {},
                       'body_fields': {},
                       'has_body': False,
                       'contract_operation': 'openConversation'},
 'list_tags': {'method': 'GET',
               'path': '/v1/tags',
               'path_fields': {},
               'query_fields': {},
               'body_fields': {},
               'has_body': False,
               'contract_operation': 'listTags'},
 'create_tag': {'method': 'POST',
                'path': '/v1/tags',
                'path_fields': {},
                'query_fields': {},
                'body_fields': {'name': 'name', 'color': 'color'},
                'has_body': True,
                'contract_operation': 'createTag'},
 'list_phases': {'method': 'GET',
                 'path': '/v1/phases',
                 'path_fields': {},
                 'query_fields': {},
                 'body_fields': {},
                 'has_body': False,
                 'contract_operation': 'listPhases'},
 'assign_conversation_phase': {'method': 'PATCH',
                               'path': '/v1/conversations/{conversationId}/phases/{phaseId}',
                               'path_fields': {'conversation_id': 'conversationId',
                                               'phase_id': 'phaseId'},
                               'query_fields': {},
                               'body_fields': {},
                               'has_body': False,
                               'contract_operation': 'assignPhaseToConversation'},
 'get_account': {'method': 'GET',
                 'path': '/v1/account',
                 'path_fields': {},
                 'query_fields': {},
                 'body_fields': {},
                 'has_body': False,
                 'contract_operation': 'getAccount'},
 'list_channels': {'method': 'GET',
                   'path': '/v1/channels',
                   'path_fields': {},
                   'query_fields': {},
                   'body_fields': {},
                   'has_body': False,
                   'contract_operation': 'listChannels'},
 'list_users': {'method': 'GET',
                'path': '/v1/users',
                'path_fields': {},
                'query_fields': {'limit': 'limit', 'offset': 'offset'},
                'body_fields': {},
                'has_body': False,
                'contract_operation': 'listUsers'},
 'list_whatsapp_templates': {'method': 'GET',
                             'path': '/v1/whatsapp/{channelId}/templates',
                             'path_fields': {'channel_id': 'channelId'},
                             'query_fields': {},
                             'body_fields': {},
                             'has_body': False,
                             'contract_operation': 'listWhatsAppTemplates'},
 'list_teams': {'method': 'GET',
                'path': '/v1/teams',
                'path_fields': {},
                'query_fields': {},
                'body_fields': {},
                'has_body': False,
                'contract_operation': 'listTeams'}}


class CliengoNode(WorkflowNode):
    integration_type = "automation-cliengo"
    connection_evidence = ConnectionEvidence(noun="Cliengo account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return CliengoFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Supply a Cliengo API token")
        config = self.config.config
        route = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, mode="json")
        path = route["path"]
        for field, wire_name in route["path_fields"].items():
            path = path.replace("{" + wire_name + "}", quote(values[field], safe=""))
        params = {wire: values[field] for field, wire in route["query_fields"].items() if field in values}
        # The API supports page/limit or offset/limit, not competing defaults.
        if "offset" in params and "page" in params:
            params.pop("page")
        body = {wire: values[field] for field, wire in route["body_fields"].items() if field in values}
        base = "https://connect.stagecliengo.com" if credential.api_token.startswith("sk_test_") else "https://connect.cliengo.com"
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        kwargs = {"params": params}
        if route["has_body"]:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(route["method"], base + path, headers=headers, **kwargs)
        if response.is_redirect:
            raise ValueError("Cliengo returned a redirect; check the token environment")
        if response.is_error:
            try:
                error = response.json()
                message = str(error.get("message") or error.get("error") or "Request rejected")
            except (ValueError, AttributeError):
                message = "Request rejected"
            message = message.replace(credential.api_token, "[redacted]")
            raise ValueError(f"Cliengo HTTP {response.status_code}: {message}")
        if not response.content:
            data = None
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Cliengo returned a non-JSON response") from None
        if isinstance(data, dict) and (data.get("error") or data.get("success") is False or isinstance(data.get("statusCode"), int) and data["statusCode"] >= 400):
            message = str(data.get("message") or data.get("error") or "Request rejected")
            raise ValueError(message.replace(credential.api_token, "[redacted]"))
        # Preserve the provider's documented envelope, including keyed conversation
        # maps and pagination, instead of guessing that every response is an array.
        if isinstance(data, dict):
            return data
        return {"data": data}

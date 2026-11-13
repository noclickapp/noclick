"""Markup AI API 1.0.0: one published API operation per workflow action.

https://docs.markup.ai/openapi.json
Lists return a single page with the provider's pagination metadata intact.
Run actions submit asynchronously by default; use the workflow reads to poll.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, Json, StrictBool, model_validator, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.markup.ai"
_JSON = {"ui:widget": "code_editor", "x-code-language": "json"}


class MarkupAiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Markup AI API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://console.markup.ai",
        "x-credential-instructions": "In the Markup AI console, open API Keys and create an API key, then paste it here without the Bearer prefix. NoClick sends it only to api.markup.ai. Connecting reads your terminology domains. Your organization must have the Style Agent enabled to run style checks.",
    })
    credential_type: Literal["markup_ai_api_key"] = Field("markup_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def editor_values(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for name, field in cls.model_fields.items():
            if (field.json_schema_extra or {}).get("ui:widget") == "code_editor" and isinstance(value.get(name), (dict, list)):
                value[name] = json.dumps(value[name])
        return value


class TermInput(_Input):
    term: str
    type: Literal["preferred", "prohibited"]
    case_sensitive: StrictBool = False


class MarkupAiGetStyleConfigConfig(_Input):
    """Get Style Agent Config."""
    operation: Literal['get_style_config'] = Field('get_style_config', json_schema_extra={"ui:hidden": True})


class MarkupAiListStyleGuidesConfig(_Input):
    """List Style Guides."""
    operation: Literal['list_style_guides'] = Field('list_style_guides', json_schema_extra={"ui:hidden": True})


class MarkupAiGetStyleGuideConfig(_Input):
    """Get Style Guide."""
    operation: Literal['get_style_guide'] = Field('get_style_guide', json_schema_extra={"ui:hidden": True})
    style_guide_id: str = Field(...)


class MarkupAiListContentProfilesConfig(_Input):
    """List Style Agent Content Profiles."""
    operation: Literal['list_content_profiles'] = Field('list_content_profiles', json_schema_extra={"ui:hidden": True})


class MarkupAiRunStyleCheckConfig(_Input):
    """Run Style Agent."""
    operation: Literal['run_style_check'] = Field('run_style_check', json_schema_extra={"ui:hidden": True})
    wait: StrictBool = Field(False)
    style_guide_id: str | None = Field(None, min_length=1, description='Style guide ID to check the document against. ``target_id`` is a deprecated alias for this field; send exactly one of the two names.')
    content_profile_id: str | None = Field(None, min_length=1, description='Language-service content profile ID for style checking.')
    domain_ids: Json[list[str] | None] = Field(None, json_schema_extra=_JSON, description='Terminology domain IDs.')
    document_ref: str | None = Field(None, min_length=1, max_length=512, description='Caller-provided document identifier for tracking across scans.')
    url: str | None = Field(None, min_length=1, description='Document URL.')
    document_name: str | None = Field(None, min_length=1, description='Document name or title.')
    webhook_url: AnyUrl | None = Field(None, min_length=1, max_length=2083, description='Optional webhook URL for async result delivery.')
    text: str = Field(..., min_length=1, max_length=100000, description='Document text to analyze.')


class MarkupAiGetStyleWorkflowConfig(_Input):
    """Get Style Agent Workflow."""
    operation: Literal['get_style_workflow'] = Field('get_style_workflow', json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(...)


class MarkupAiListAgentsConfig(_Input):
    """List Agents."""
    operation: Literal['list_agents'] = Field('list_agents', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    category: str | None = Field(None)
    include_unavailable: StrictBool = Field(False)


class MarkupAiGetAgentConfig(_Input):
    """Get Agent."""
    operation: Literal['get_agent'] = Field('get_agent', json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(...)


class MarkupAiRunAgentConfig(_Input):
    """Run Agent."""
    operation: Literal['run_agent'] = Field('run_agent', json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(...)
    wait: StrictBool = Field(False)
    agents: Json[list[str] | None] = Field(None, json_schema_extra=_JSON, description='Agent IDs to execute. Resolved to agent names server-side.')
    domain_ids: Json[list[str] | None] = Field(None, json_schema_extra=_JSON, description='Terminology domain IDs.')
    document_ref: str | None = Field(None, min_length=1, max_length=512, description='Caller-provided document identifier for tracking across scans.')
    url: str | None = Field(None, min_length=1, description='Document URL.')
    document_name: str | None = Field(None, min_length=1, description='Document name or title.')
    style_guide_id: str | None = Field(None, min_length=1, description='Style guide ID to check the document against. ``target_id`` is a deprecated alias for this field; send exactly one of the two names.')
    content_profile_id: str | None = Field(None, min_length=1, description='Language-service content profile ID for style checking.')
    goal: str | None = Field(None, min_length=1, max_length=500, description='Document goal for agent recommendation.')
    persona_id: str | None = Field(None, min_length=1, description='Agent configuration UUID for persona selection. Used by: persona. Retrieve valid IDs from GET /personas.')
    persona_ids: Json[list[str] | None] = Field(None, json_schema_extra=_JSON, description='Persona UUIDs to analyze against, max 3. Used by: persona. Send this or persona_id, not both. Retrieve valid IDs from GET /personas.')
    no_personas: StrictBool = Field(False, description="Review the document without any reader's perspective. Set this when no persona was chosen on purpose; leave it unset to let the review pick the readers a document is written for. Cannot be sent with persona_ids.")
    voice_profile_id: str | None = Field(None, min_length=1, description='Agent configuration UUID for brand voice profile selection. Used by: brand_voice. Retrieve valid IDs from GET /brand-voice-profiles.')
    webhook_url: AnyUrl | None = Field(None, min_length=1, max_length=2083, description='Optional webhook URL for async result delivery.')
    text: str = Field(..., min_length=1, max_length=100000, description='Document text to analyze.')
    issues: Json[list[dict[str, Any]] | None] = Field(None, json_schema_extra=_JSON, description="Issues from a previous run to act on, each exactly as returned in that run's result. Supported by agents that apply or rework existing findings; when provided, such an agent works from these instead of re-detecting. Positions must refer to the ``text`` in this request. Other agents ignore this field.")
    generate_fixes: StrictBool | None = Field(None, description='When true, agents that apply existing findings also draft a fix for findings that carry no suggested replacement. Every drafted fix is verified in context before it is applied; a finding whose draft fails that verification is returned unapplied and its text is left unchanged. Off by default. Other agents ignore this field.')

    @model_validator(mode="after")
    def personas(self):
        if self.persona_id is not None and self.persona_ids is not None:
            raise ValueError("Supply persona_id or persona_ids, never both")
        if self.persona_ids is not None and (len(self.persona_ids) > 3 or self.no_personas):
            raise ValueError("Supply at most three personas, or select no_personas")
        return self


class MarkupAiGetPersonaConfig(_Input):
    """Get Persona."""
    operation: Literal['get_persona'] = Field('get_persona', json_schema_extra={"ui:hidden": True})
    persona_id: UUID = Field(...)


class MarkupAiGetWorkflowConfig(_Input):
    """Get Workflow Status."""
    operation: Literal['get_workflow'] = Field('get_workflow', json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(...)


class MarkupAiCancelWorkflowConfig(_Input):
    """Cancel Workflow."""
    operation: Literal['cancel_workflow'] = Field('cancel_workflow', json_schema_extra={"ui:hidden": True})
    workflow_id: str = Field(...)


class MarkupAiSearchTerminologyConfig(_Input):
    """Search Terminology."""
    operation: Literal['search_terminology'] = Field('search_terminology', json_schema_extra={"ui:hidden": True})
    query: str = Field(...)
    domain_ids: Json[list[str] | None] = Field(None, json_schema_extra=_JSON)


class MarkupAiListTermSetsConfig(_Input):
    """List Term Sets."""
    operation: Literal['list_term_sets'] = Field('list_term_sets', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    search_term: str | None = Field(None)
    domain_ids: Json[list[UUID] | None] = Field(None, json_schema_extra=_JSON)
    has_context: StrictBool | None = Field(None)


class MarkupAiCreateTermSetConfig(_Input):
    """Create Term Set."""
    operation: Literal['create_term_set'] = Field('create_term_set', json_schema_extra={"ui:hidden": True})
    context: str = Field(...)
    term_type: Literal['preferred', 'prohibited'] | None = Field(None)
    context_polarity: Literal['include', 'exclude'] | None = Field(None)
    terms: Json[list[TermInput] | None] = Field(None, json_schema_extra=_JSON)
    domain_ids: Json[list[UUID] | None] = Field(None, json_schema_extra=_JSON)


class MarkupAiGetTermSetConfig(_Input):
    """Get Term Set."""
    operation: Literal['get_term_set'] = Field('get_term_set', json_schema_extra={"ui:hidden": True})
    term_set_id: UUID = Field(...)


class MarkupAiUpdateTermSetConfig(_Input):
    """Update Term Set."""
    operation: Literal['update_term_set'] = Field('update_term_set', json_schema_extra={"ui:hidden": True})
    term_set_id: UUID = Field(...)
    context: str | None = Field(None)
    term_type: Literal['preferred', 'prohibited'] | None = Field(None)
    context_polarity: Literal['include', 'exclude'] | None = Field(None)
    domain_ids: Json[list[UUID] | None] = Field(None, json_schema_extra=_JSON)

    clear_context: StrictBool = Field(False, description="Clear the term set context by sending JSON null. Leave context unset when using this option.")


class MarkupAiDeleteTermSetConfig(_Input):
    """Delete Term Set."""
    operation: Literal['delete_term_set'] = Field('delete_term_set', json_schema_extra={"ui:hidden": True})
    term_set_id: UUID = Field(...)


class MarkupAiCreateTermConfig(_Input):
    """Create Term."""
    operation: Literal['create_term'] = Field('create_term', json_schema_extra={"ui:hidden": True})
    term_set_id: UUID = Field(...)
    term: str = Field(...)
    type: Literal['preferred', 'prohibited'] = Field(...)
    case_sensitive: StrictBool = Field(False)


class MarkupAiGetTermConfig(_Input):
    """Get Term."""
    operation: Literal['get_term'] = Field('get_term', json_schema_extra={"ui:hidden": True})
    term_set_id: UUID = Field(...)
    term_id: UUID = Field(...)


class MarkupAiUpdateTermConfig(_Input):
    """Update Term."""
    operation: Literal['update_term'] = Field('update_term', json_schema_extra={"ui:hidden": True})
    term_set_id: UUID = Field(...)
    term_id: UUID = Field(...)
    term: str = Field(...)
    type: Literal['preferred', 'prohibited'] = Field(...)
    case_sensitive: StrictBool | None = Field(None)


class MarkupAiDeleteTermConfig(_Input):
    """Delete Term."""
    operation: Literal['delete_term'] = Field('delete_term', json_schema_extra={"ui:hidden": True})
    term_set_id: UUID = Field(...)
    term_id: UUID = Field(...)


class MarkupAiListDomainsConfig(_Input):
    """List Domains."""
    operation: Literal['list_domains'] = Field('list_domains', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    search: str | None = Field(None)


class MarkupAiListPersonasConfig(_Input):
    """List Personas."""
    operation: Literal['list_personas'] = Field('list_personas', json_schema_extra={"ui:hidden": True})


class MarkupAiListVoiceProfilesConfig(_Input):
    """List Profiles."""
    operation: Literal['list_voice_profiles'] = Field('list_voice_profiles', json_schema_extra={"ui:hidden": True})


# Markup AI's own MCP server: agents get its tools through a person's Markup AI sign-in.
MarkupAiMcpCredential = mcp_credential("markup_ai", "https://api.markup.ai/mcp/", app="Markup AI")
MarkupAiCredential = Union[MarkupAiAPIKeyCredential, MarkupAiMcpCredential]


MarkupAiConfig = Annotated[Union[
    MarkupAiGetStyleConfigConfig,
    MarkupAiListStyleGuidesConfig,
    MarkupAiGetStyleGuideConfig,
    MarkupAiListContentProfilesConfig,
    MarkupAiRunStyleCheckConfig,
    MarkupAiGetStyleWorkflowConfig,
    MarkupAiListAgentsConfig,
    MarkupAiGetAgentConfig,
    MarkupAiRunAgentConfig,
    MarkupAiGetPersonaConfig,
    MarkupAiGetWorkflowConfig,
    MarkupAiCancelWorkflowConfig,
    MarkupAiSearchTerminologyConfig,
    MarkupAiListTermSetsConfig,
    MarkupAiCreateTermSetConfig,
    MarkupAiGetTermSetConfig,
    MarkupAiUpdateTermSetConfig,
    MarkupAiDeleteTermSetConfig,
    MarkupAiCreateTermConfig,
    MarkupAiGetTermConfig,
    MarkupAiUpdateTermConfig,
    MarkupAiDeleteTermConfig,
    MarkupAiListDomainsConfig,
    MarkupAiListPersonasConfig,
    MarkupAiListVoiceProfilesConfig
], Field(discriminator="operation")]

ROUTES = {'get_style_config': {'method': 'GET',
                      'path': '/style-agent/config',
                      'path_fields': [],
                      'query_fields': [],
                      'body_fields': []},
 'list_style_guides': {'method': 'GET',
                       'path': '/style-agent/style-guides',
                       'path_fields': [],
                       'query_fields': [],
                       'body_fields': []},
 'get_style_guide': {'method': 'GET',
                     'path': '/style-agent/style-guides/{style_guide_id}',
                     'path_fields': ['style_guide_id'],
                     'query_fields': [],
                     'body_fields': []},
 'list_content_profiles': {'method': 'GET',
                           'path': '/style-agent/content-profiles',
                           'path_fields': [],
                           'query_fields': [],
                           'body_fields': []},
 'run_style_check': {'method': 'POST',
                     'path': '/style-agent/run',
                     'path_fields': [],
                     'query_fields': ['wait'],
                     'body_fields': ['style_guide_id',
                                     'content_profile_id',
                                     'domain_ids',
                                     'document_ref',
                                     'url',
                                     'document_name',
                                     'webhook_url',
                                     'text']},
 'get_style_workflow': {'method': 'GET',
                        'path': '/style-agent/workflows/{workflow_id}',
                        'path_fields': ['workflow_id'],
                        'query_fields': [],
                        'body_fields': []},
 'list_agents': {'method': 'GET',
                 'path': '/agents',
                 'path_fields': [],
                 'query_fields': ['page', 'page_size', 'category', 'include_unavailable'],
                 'body_fields': []},
 'get_agent': {'method': 'GET',
               'path': '/agents/{agent_id}',
               'path_fields': ['agent_id'],
               'query_fields': [],
               'body_fields': []},
 'run_agent': {'method': 'POST',
               'path': '/agents/{agent_id}/run',
               'path_fields': ['agent_id'],
               'query_fields': ['wait'],
               'body_fields': ['agents',
                               'domain_ids',
                               'document_ref',
                               'url',
                               'document_name',
                               'style_guide_id',
                               'content_profile_id',
                               'goal',
                               'persona_id',
                               'persona_ids',
                               'no_personas',
                               'voice_profile_id',
                               'webhook_url',
                               'text',
                               'issues',
                               'generate_fixes']},
 'get_persona': {'method': 'GET',
                 'path': '/personas/{persona_id}',
                 'path_fields': ['persona_id'],
                 'query_fields': [],
                 'body_fields': []},
 'get_workflow': {'method': 'GET',
                  'path': '/agents/workflows/{workflow_id}',
                  'path_fields': ['workflow_id'],
                  'query_fields': [],
                  'body_fields': []},
 'cancel_workflow': {'method': 'DELETE',
                     'path': '/agents/workflows/{workflow_id}',
                     'path_fields': ['workflow_id'],
                     'query_fields': [],
                     'body_fields': []},
 'search_terminology': {'method': 'GET',
                        'path': '/brand-terms/search',
                        'path_fields': [],
                        'query_fields': ['query', 'domain_ids'],
                        'body_fields': []},
 'list_term_sets': {'method': 'GET',
                    'path': '/brand-terms/term-sets',
                    'path_fields': [],
                    'query_fields': ['page', 'page_size', 'search_term', 'domain_ids', 'has_context'],
                    'body_fields': []},
 'create_term_set': {'method': 'POST',
                     'path': '/brand-terms/term-sets',
                     'path_fields': [],
                     'query_fields': [],
                     'body_fields': ['context', 'term_type', 'context_polarity', 'terms', 'domain_ids']},
 'get_term_set': {'method': 'GET',
                  'path': '/brand-terms/term-sets/{term_set_id}',
                  'path_fields': ['term_set_id'],
                  'query_fields': [],
                  'body_fields': []},
 'update_term_set': {'method': 'PATCH',
                     'path': '/brand-terms/term-sets/{term_set_id}',
                     'path_fields': ['term_set_id'],
                     'query_fields': [],
                     'body_fields': ['context', 'term_type', 'context_polarity', 'domain_ids']},
 'delete_term_set': {'method': 'DELETE',
                     'path': '/brand-terms/term-sets/{term_set_id}',
                     'path_fields': ['term_set_id'],
                     'query_fields': [],
                     'body_fields': []},
 'create_term': {'method': 'POST',
                 'path': '/brand-terms/term-sets/{term_set_id}/terms',
                 'path_fields': ['term_set_id'],
                 'query_fields': [],
                 'body_fields': ['term', 'type', 'case_sensitive']},
 'get_term': {'method': 'GET',
              'path': '/brand-terms/term-sets/{term_set_id}/terms/{term_id}',
              'path_fields': ['term_set_id', 'term_id'],
              'query_fields': [],
              'body_fields': []},
 'update_term': {'method': 'PUT',
                 'path': '/brand-terms/term-sets/{term_set_id}/terms/{term_id}',
                 'path_fields': ['term_set_id', 'term_id'],
                 'query_fields': [],
                 'body_fields': ['term', 'type', 'case_sensitive']},
 'delete_term': {'method': 'DELETE',
                 'path': '/brand-terms/term-sets/{term_set_id}/terms/{term_id}',
                 'path_fields': ['term_set_id', 'term_id'],
                 'query_fields': [],
                 'body_fields': []},
 'list_domains': {'method': 'GET',
                  'path': '/brand-terms/domains',
                  'path_fields': [],
                  'query_fields': ['page', 'page_size', 'search'],
                  'body_fields': []},
 'list_personas': {'method': 'GET', 'path': '/personas', 'path_fields': [], 'query_fields': [], 'body_fields': []},
 'list_voice_profiles': {'method': 'GET',
                         'path': '/brand-voice-profiles',
                         'path_fields': [],
                         'query_fields': [],
                         'body_fields': []}}

class MarkupAiFullConfig(NodeConfig[MarkupAiConfig, MarkupAiCredential]):
    pass


class MarkupAiNode(WorkflowNode):
    integration_type = "automation-markup-ai"
    credential_provider_labels = {"markup_ai": "Markup AI Account"}
    connection_evidence = ConnectionEvidence(noun="terminology domains", operation="list_domains", label_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return MarkupAiFullConfig

    async def execute(self, input_data):
        if not self.config.credentials:
            raise ValueError("Attach a Markup AI API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for name in route["path_fields"]:
            value = str(values[name])
            if not value or value in {".", ".."} or any(c in value for c in "/\\?#"):
                raise ValueError("Use a single Markup AI resource identifier")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        params = {name: values[name] for name in route["query_fields"] if name in values}
        body = {name: values[name] for name in route["body_fields"] if name in values}
        if config.operation == "update_term_set" and config.clear_context:
            if config.context:
                raise ValueError("Supply context or clear_context, never both")
            body["context"] = None
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=120, trust_env=False, follow_redirects=False) as client:
                response = await client.request(route["method"], BASE + path, params=params,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    **({"json": body} if route["body_fields"] else {}))
            if not 200 <= response.status_code < 300:
                message = "Markup AI request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        detail = error.get("detail") or error.get("message")
                        if isinstance(detail, str):
                            message = detail.replace(key, "[redacted]")[:1000]
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code, "message": message}
            if response.status_code == 204:
                return {"status": "success", "http_status": 204, "data": None}
            if len(response.content) > 10_000_000:
                raise ValueError("Markup AI response exceeded the JSON size limit")
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Expected Markup AI JSON object or list")
            result = {"status": "success", "http_status": response.status_code, "data": payload}
            if config.operation == "list_domains":
                domains = payload.get("domains") if isinstance(payload, dict) else None
                if not isinstance(domains, list):
                    raise ValueError("Markup AI did not return terminology domains")
                result["items"] = domains
            return result
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "message": "Markup AI request could not be confirmed"}

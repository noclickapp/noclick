"""Botsonic Business API, pinned to the provider's published OpenAPI 1.0.0.

Bot-scoped token only; list operations return a single page with provider pagination.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class BotsonicCredential(BaseModel):
    model_config = ConfigDict(title="Botsonic API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-instructions": "Business access is required. In Botsonic, open your bot, then Share > API Token. Paste the bot token below.", "x-credential-url": "https://api.botsonic.ai/docs"})
    credential_type: Literal["botsonic_api_token"] = Field("botsonic_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Bot API Token", min_length=1, repr=False,
        description="Paste the bot API token from Share > API Token. Business access is required.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste a bot API token without spaces or control characters")
        return value


class BotsonicGenerateResponseConfig(BaseModel):
    """Generation endpoint supporting synchronous response."""
    operation: Literal['generate_response'] = Field('generate_response', json_schema_extra={"ui:hidden": True})
    input_text: str = Field(..., min_length=1, description='User question for bot')
    chat_id: str = Field(..., description='chat_id for given chat')
    user_unique_identifier: str | None = Field(None, description='Can be passed to store some additional user data in inbox')
    full_history: bool | None = Field(None, description='if true, will return full history of chat till now')


class BotsonicListFaqsConfig(BaseModel):
    """Get all FAQs for a bot in paginated format."""
    operation: Literal['list_faqs'] = Field('list_faqs', json_schema_extra={"ui:hidden": True})
    search_query: str | None = Field(None, description='Search for bot-faq matching particluar query')
    sort_by: Literal['id', 'bot_id', 'question', 'answer', 'error_reason', 'status', 'characters', 'migration_status', 'created_at', 'updated_at'] | None = Field(None, description='Select attribute to sort by')
    sort_order: Literal['asc', 'desc'] | None = Field(None, description='Select sorting order')
    page: int = Field(1, ge=1.0)
    size: int = Field(50, ge=1.0, le=100.0)


class BotsonicCreateFaqConfig(BaseModel):
    """Create bot faq."""
    operation: Literal['create_faq'] = Field('create_faq', json_schema_extra={"ui:hidden": True})
    question: str = Field(..., description='The question for the FAQ entry.')
    answer: str = Field(..., description='The answer to the FAQ question.')


class BotsonicDeleteFaqConfig(BaseModel):
    """Delete bot faq."""
    operation: Literal['delete_faq'] = Field('delete_faq', json_schema_extra={"ui:hidden": True})
    faq_id: str = Field(..., description='faq_id of specific faq to delete')


class BotsonicListTrainingDataConfig(BaseModel):
    """Get all Bot Data in a paginated format."""
    operation: Literal['list_training_data'] = Field('list_training_data', json_schema_extra={"ui:hidden": True})
    search_query: str | None = Field(None, description='Search for data matching particluar query')
    sort_by: Literal['id', 'bot_id', 'url', 'title', 'file_type', 'is_private', 'error_reason', 'status', 'sitemap_id', 'characters', 'last_trained_at', 'resync_job_id', 'integration_id', 'third_party_id', 'container_id', 'storage_account_id', 'is_paused', 'is_added_via_ability', 'is_deleted', 'is_in_waiting_room', 'migration_status', 'created_at', 'updated_at'] = Field('updated_at', description='Select attribute to sort by')
    sort_order: Literal['asc', 'desc'] = Field('desc', description='Select sorting order')
    page: int = Field(1, ge=1.0)
    size: int = Field(50, ge=1.0, le=100.0)


class BotsonicListConversationsConfig(BaseModel):
    """Get all conversations in paginated format."""
    operation: Literal['list_conversations'] = Field('list_conversations', json_schema_extra={"ui:hidden": True})
    search_query: str | None = Field(None, description='Search for data matching particluar query')
    sort_by: Literal['recent', 'negative', 'positive'] = Field('recent', description='Select conversation type to sort by')
    sort_order: Literal['asc', 'desc'] = Field('desc', description='Select sorting order')
    updated_after: str | None = Field(None, description='Filter conversations updated after this datetime (ISO 8601). Example: 2024-01-01T00:00:00Z')
    updated_before: str | None = Field(None, description='Filter conversations updated before this datetime (ISO 8601). Example: 2024-01-01T00:00:00Z')
    page: int = Field(1, ge=1.0)
    size: int = Field(50, ge=1.0, le=100.0)


class BotsonicListConversationsWithSourceConfig(BaseModel):
    """Get All Conversations With Source."""
    operation: Literal['list_conversations_with_source'] = Field('list_conversations_with_source', json_schema_extra={"ui:hidden": True})
    chat_ids: list[str] = Field([])
    search_query: str | None = Field(None, description='Search for data matching particluar query')
    sort_by: Literal['recent', 'negative', 'positive'] = Field('recent', description='Select conversation type to sort by')
    sort_order: Literal['asc', 'desc'] = Field('desc', description='Select sorting order')
    updated_after: str | None = Field(None, description='Filter conversations updated after this datetime (ISO 8601). Example: 2024-01-01T00:00:00Z')
    updated_before: str | None = Field(None, description='Filter conversations updated before this datetime (ISO 8601). Example: 2024-01-01T00:00:00Z')
    page: int = Field(1, ge=1.0)
    size: int = Field(50, ge=1.0, le=100.0)


class BotsonicGetConversationConfig(BaseModel):
    """Get specific conversation by chat_id."""
    operation: Literal['get_conversation'] = Field('get_conversation', json_schema_extra={"ui:hidden": True})
    chat_id: str = Field(..., description='chat_id of specific conversation')


class BotsonicEndChatConfig(BaseModel):
    """End a chat conversation."""
    operation: Literal['end_chat'] = Field('end_chat', json_schema_extra={"ui:hidden": True})
    chat_id: str = Field(..., description='chat_id of specific conversation')
    status: Literal['liked', 'disliked', 'none'] = Field('none', description='status of chat')
    feedback: str | None = Field(None, description='feedback for chat')


class BotsonicDeleteTrainingDataConfig(BaseModel):
    """Delete particluar bot data."""
    operation: Literal['delete_training_data'] = Field('delete_training_data', json_schema_extra={"ui:hidden": True})
    data_id: str = Field(..., description='data_id of specific bot data to delete')


class BotsonicUploadUrlsConfig(BaseModel):
    """Upsert multiple URL's ( with validation ) from a bot."""
    operation: Literal['upload_urls'] = Field('upload_urls', json_schema_extra={"ui:hidden": True})
    urls: list[str] = Field(..., description='A list of URLs to be uploaded in bulk.')
    sitemap_id: str | None = Field(None, description='An optional sitemap ID associated with the uploaded URLs.')
    is_sitemap: bool = Field(False, description='Set to `True` if the uploaded URLs are from a sitemap; otherwise, use `False`.')
    sitemap_root: str | None = Field(None, description='The root URL of the sitemap if `is_sitemap` is set to `True`.')
    ability_id: str | None = Field(None)
    is_crawled: bool = Field(False)


class BotsonicUploadFileConfig(BaseModel):
    """Upsert multiple URL's ( with validation ) from a bot."""
    operation: Literal['upload_file'] = Field('upload_file', json_schema_extra={"ui:hidden": True})
    id: str = Field(...)
    bot_id: str = Field(...)
    file_url: str = Field(...)
    file_name: str | None = Field(None)


class BotsonicUploadTextConfig(BaseModel):
    """Upload Text."""
    operation: Literal['upload_text'] = Field('upload_text', json_schema_extra={"ui:hidden": True})
    id: str = Field(...)
    bot_id: str = Field(...)
    title: str | None = Field(None)
    text: str = Field(...)


class BotsonicListStarterQuestionsConfig(BaseModel):
    """Get all Starter questions for a bot in paginated format."""
    operation: Literal['list_starter_questions'] = Field('list_starter_questions', json_schema_extra={"ui:hidden": True})
    search_query: str | None = Field(None, description='Search for bot-starter-question matching particluar query')
    sort_by: Literal['id', 'bot_id', 'question', 'answer', 'order', 'created_at', 'updated_at'] = Field('order', description='Select attribute to sort by')
    sort_order: Literal['asc', 'desc'] = Field('asc', description='Select sorting order')
    page: int = Field(1, ge=1.0)
    size: int = Field(50, ge=1.0, le=100.0)


class BotsonicCreateStarterQuestionConfig(BaseModel):
    """Create starter question."""
    operation: Literal['create_starter_question'] = Field('create_starter_question', json_schema_extra={"ui:hidden": True})
    question: str = Field(..., min_length=1, description='a starter question')
    answer: str = Field(..., min_length=1, description='answer for given question')
    order: int = Field(0, description='Set order in which this question appears')


class BotsonicDeleteStarterQuestionConfig(BaseModel):
    """Delete starter question."""
    operation: Literal['delete_starter_question'] = Field('delete_starter_question', json_schema_extra={"ui:hidden": True})
    starter_question_id: str = Field(..., description='starter_question_id of specific starter question to delete')


class BotsonicUpdateStarterQuestionConfig(BaseModel):
    """Update starter question."""
    operation: Literal['update_starter_question'] = Field('update_starter_question', json_schema_extra={"ui:hidden": True})
    starter_question_id: str = Field(..., description='starter_question_id of specific starter question to update')
    question: str | None = Field(None, min_length=1, description='a starter question')
    answer: str | None = Field(None, min_length=1, description='answer for given question')
    order: int | None = Field(None, description='Set order in which this question appears')


class BotsonicListStarterPresetsConfig(BaseModel):
    """Get All Starter Presets By Bot Id."""
    operation: Literal['list_starter_presets'] = Field('list_starter_presets', json_schema_extra={"ui:hidden": True})


BotsonicConfig = Annotated[Union[BotsonicGenerateResponseConfig, BotsonicListFaqsConfig, BotsonicCreateFaqConfig, BotsonicDeleteFaqConfig, BotsonicListTrainingDataConfig, BotsonicListConversationsConfig, BotsonicListConversationsWithSourceConfig, BotsonicGetConversationConfig, BotsonicEndChatConfig, BotsonicDeleteTrainingDataConfig, BotsonicUploadUrlsConfig, BotsonicUploadFileConfig, BotsonicUploadTextConfig, BotsonicListStarterQuestionsConfig, BotsonicCreateStarterQuestionConfig, BotsonicDeleteStarterQuestionConfig, BotsonicUpdateStarterQuestionConfig, BotsonicListStarterPresetsConfig], Field(discriminator="operation")]


class BotsonicFullConfig(NodeConfig[BotsonicConfig, BotsonicCredential]):
    pass


ROUTES = {'generate_response': ('POST',
                       '/v1/botsonic/generate',
                       {'path': [],
                        'query': [],
                        'body': ['input_text',
                                 'chat_id',
                                 'user_unique_identifier',
                                 'full_history']}),
 'list_faqs': ('GET',
               '/v1/business/bot-faq/all',
               {'path': [],
                'query': ['search_query', 'sort_by', 'sort_order', 'page', 'size'],
                'body': []}),
 'create_faq': ('POST',
                '/v1/business/bot-faq',
                {'path': [], 'query': [], 'body': ['question', 'answer']}),
 'delete_faq': ('DELETE',
                '/v1/business/bot-faq/{faq_id}',
                {'path': ['faq_id'], 'query': [], 'body': []}),
 'list_training_data': ('GET',
                        '/v1/business/bot-data/all',
                        {'path': [],
                         'query': ['search_query', 'sort_by', 'sort_order', 'page', 'size'],
                         'body': []}),
 'list_conversations': ('GET',
                        '/v1/business/bot-data/conversations/all',
                        {'path': [],
                         'query': ['search_query',
                                   'sort_by',
                                   'sort_order',
                                   'updated_after',
                                   'updated_before',
                                   'page',
                                   'size'],
                         'body': []}),
 'list_conversations_with_source': ('GET',
                                    '/v1/business/bot-data/conversations/with-source',
                                    {'path': [],
                                     'query': ['chat_ids',
                                               'search_query',
                                               'sort_by',
                                               'sort_order',
                                               'updated_after',
                                               'updated_before',
                                               'page',
                                               'size'],
                                     'body': []}),
 'get_conversation': ('GET',
                      '/v1/business/bot-data/conversations/{chat_id}',
                      {'path': ['chat_id'], 'query': [], 'body': []}),
 'end_chat': ('POST',
              '/v1/business/bot-data/conversations/{chat_id}/end-chat',
              {'path': ['chat_id'], 'query': [], 'body': ['status', 'feedback']}),
 'delete_training_data': ('DELETE',
                          '/v1/business/bot-data/{data_id}',
                          {'path': ['data_id'], 'query': [], 'body': []}),
 'upload_urls': ('POST',
                 '/v1/business/bot-data/bulk-upsert-urls',
                 {'path': [],
                  'query': [],
                  'body': ['urls',
                           'sitemap_id',
                           'is_sitemap',
                           'sitemap_root',
                           'ability_id',
                           'is_crawled']}),
 'upload_file': ('POST',
                 '/v1/business/bot-data/upload-file',
                 {'path': [], 'query': [], 'body': ['id', 'bot_id', 'file_url', 'file_name']}),
 'upload_text': ('POST',
                 '/v1/business/bot-data/upload-text',
                 {'path': [], 'query': [], 'body': ['id', 'bot_id', 'title', 'text']}),
 'list_starter_questions': ('GET',
                            '/v1/business/bot-starter-questions/all',
                            {'path': [],
                             'query': ['search_query', 'sort_by', 'sort_order', 'page', 'size'],
                             'body': []}),
 'create_starter_question': ('POST',
                             '/v1/business/bot-starter-questions',
                             {'path': [], 'query': [], 'body': ['question', 'answer', 'order']}),
 'delete_starter_question': ('DELETE',
                             '/v1/business/bot-starter-questions/{starter_question_id}',
                             {'path': ['starter_question_id'], 'query': [], 'body': []}),
 'update_starter_question': ('PATCH',
                             '/v1/business/bot-starter-questions/{starter_question_id}',
                             {'path': ['starter_question_id'],
                              'query': [],
                              'body': ['question', 'answer', 'order']}),
 'list_starter_presets': ('GET',
                          '/v1/business/bot-starter-presets/all',
                          {'path': [], 'query': [], 'body': []})}


class BotsonicNode(WorkflowNode):
    integration_type = "automation-botsonic"
    connection_evidence = ConnectionEvidence(operation="list_faqs", noun="FAQs")

    @classmethod
    def get_config_model(cls):
        return BotsonicFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Botsonic bot API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, path, fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for name in fields["path"]:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {k: values[k] for k in fields["query"] if k in values}
        body = {k: values[k] for k in fields["body"] if k in values}
        headers = {"Accept": "application/json", "token" if config.operation == "generate_response" else "X-BOT-KEY": token}
        kwargs = {"params": params, "headers": headers}
        if fields["body"]:
            kwargs["json"] = body
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://api.botsonic.ai" + path, **kwargs)
        if response.status_code >= 300:
            detail = response.text.replace(token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": detail}
        data = response.json() if response.content else None
        return {"status": "success", "data": data}

"""APIpie's published v1 JSON API. Each action issues one documented request.

List operations return a single provider page; use offset/pagination_token to continue.
"""
from typing import Annotated, Any, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

class ApipieAICredential(BaseModel):
    model_config = ConfigDict(title="Apipie AI API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "api_key", "x-credential-url": "https://apipie.ai/profile",
        "x-credential-instructions": "Paste your APIpie API key from your profile. NoClick verifies it by reading the app's current state settings."})
    credential_type: Literal["apipie_ai_api_key"] = Field("apipie_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Message(Input):
    role: Literal["assistant", "system", "user"]
    content: str

class CreateChatCompletionConfig(Input):
    """Chat Completions."""
    operation: Literal['create_chat_completion'] = Field('create_chat_completion', json_schema_extra={"ui:hidden": True})
    messages: list[Message] = Field(...)
    user: Optional[str] = Field(None, description='Unique identifier for the user, enabling tenant observability for usage and billing, and providing tenant services for memory and inline_cli.')
    model: str = Field(..., description='Language Model to use, comma separated, up to 5 models. Check our /models route for list of language models. Cannot use provider option with multi-model.')
    provider: Optional[str] = Field(None, description='AI Service Provider to use, omit provider and we will automatically use the most responsive provider. Optionally you can include provider with the model instead such as model: provider/model')
    temperature: Optional[float] = Field(None, ge=0, le=2, description='Influences the randomness in the selection process of the next token. Lower values make the model more deterministic, while higher values increase diversity but might reduce coherence.')
    max_tokens: Optional[int] = Field(None, ge=1, description='Max tokens used to generate a response')

class CreateEmbeddingConfig(Input):
    """Embeddings LLM."""
    operation: Literal['create_embedding'] = Field('create_embedding', json_schema_extra={"ui:hidden": True})
    model: str = Field(..., description='Model to use for generating embeddings.')
    input: str = Field(..., description='Input text to generate embeddings for.')
    encoding_format: Optional[Literal['float', 'np']] = Field(None, description='Format of the output encoding. Only supported by OpenAI')
    dimensions: Optional[int] = Field(None, le=1536, description='Number of dimensions for the embedding vector. Maximum value is 384-1536 check the models route for max_tokens per model. Only supported by OpenAI')

class GenerateImageConfig(Input):
    """Image Generation."""
    operation: Literal['generate_image'] = Field('generate_image', json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., description='Text description of the desired image(s)')
    model: Optional[str] = Field(None, description='The model to use for image generation')
    n: Optional[int] = Field(None, ge=1, le=1, description='The number of images to generate, we currently only support one at a time')
    size: Optional[str] = Field(None, description='The size of the generated images')
    quality: Optional[str] = Field(None, description='The quality of the image that will be generated')
    style: Optional[str] = Field(None, description='The style of the generated images the options are vivid and natural and does not apply to all providers')
    seed: Optional[int] = Field(None, ge=0, le=2147483647, description='A randomness initializer for image reproducibility. Check specific models for compatibility.')

class GetStateConfig(Input):
    """Get current state settings."""
    operation: Literal['get_state'] = Field('get_state', json_schema_extra={"ui:hidden": True})
    user: Optional[str] = Field(None)
    app_name: Optional[str] = Field(None, min_length=1, max_length=256, pattern='^[A-Za-z0-9 _+-]{1,256}$')

class UpdateStateConfig(Input):
    """Create/Update state settings(merge).."""
    operation: Literal['update_state'] = Field('update_state', json_schema_extra={"ui:hidden": True})
    enable_user_states: Optional[bool] = Field(None, description='If true, scope is per-user (user_id + user). If false, scope is per-app (user_id + app label).')
    user: Optional[str] = Field(None, description='Required when enable_user_states=true. Identifies the end-user.')
    enable_inline_cli: Optional[bool] = Field(None, description="Enable a command line CLI for state management at the prompt, use ':help' in the prompt to any LLM for more details")
    gui_only: Optional[bool] = Field(None, description='When true, state configuration can only be performed through the APIpie GUI and cannot be edited via API or inline cli for this API key.')
    settings: Optional[dict[str, Any]] = Field(None)
    delete: Optional[list[str]] = Field(None, description='Keys to remove from the existing settings (partial delete). Use POST to perform partial key deletes.')
    app_name: Optional[str] = Field(None, min_length=1, max_length=256, pattern='^[A-Za-z0-9 _+-]{1,256}$')
    @model_validator(mode="after")
    def user_state(self):
        if self.enable_user_states and not self.user:
            raise ValueError("Provide user when enabling per-user state")
        return self

class DeleteStateConfig(Input):
    """Delete entire state records."""
    operation: Literal['delete_state'] = Field('delete_state', json_schema_extra={"ui:hidden": True})
    user: Optional[str] = Field(None)
    app_name: Optional[str] = Field(None, min_length=1, max_length=256, pattern='^[A-Za-z0-9 _+-]{1,256}$')

class ListQueriesConfig(Input):
    """Queries History."""
    operation: Literal['list_queries'] = Field('list_queries', json_schema_extra={"ui:hidden": True})
    limit: Optional[int] = Field(None, ge=0, le=100)
    offset: Optional[int] = Field(None, ge=0)
    show: Optional[Literal['all', 'hourly', 'daily', 'weekly']] = Field(None)
    days: Optional[int] = Field(None, ge=1)
    user: Optional[str] = Field(None, max_length=14, pattern='^[a-zA-Z0-9]+$')
    app: Optional[str] = Field(None, max_length=14, pattern='^[a-zA-Z0-9]+$')
    provider: Optional[str] = Field(None, max_length=14, pattern='^[a-zA-Z0-9]+$')
    route: Optional[str] = Field(None, max_length=14, pattern='^[a-zA-Z0-9]+$')

class ListModelsConfig(Input):
    """Fetch Models."""
    operation: Literal['list_models'] = Field('list_models', json_schema_extra={"ui:hidden": True})
    type: Optional[Literal['llm', 'vision', 'embedding', 'image', 'voice', 'moderation', 'coding', 'free']] = Field(None)
    subtype: Optional[Literal['chat', 'fill-mask', 'question-answering', 'tts', 'stt', 'multimodal']] = Field(None)
    provider: Optional[str] = Field(None)
    enabled: Optional[Literal[1, 0]] = Field(None)

class ListDetailedModelsConfig(Input):
    """Fetch Detailed Models."""
    operation: Literal['list_detailed_models'] = Field('list_detailed_models', json_schema_extra={"ui:hidden": True})
    type: Optional[str] = Field(None)
    provider: Optional[str] = Field(None)
    model: Optional[str] = Field(None)

class CreateVectorCollectionConfig(Input):
    """Create a new vector collection."""
    operation: Literal['create_vector_collection'] = Field('create_vector_collection', json_schema_extra={"ui:hidden": True})
    collection_name: str = Field(...)
    dimension: int = Field(...)
    vector_provider: Optional[Literal['pinecone', 'qdrant']] = Field(None, description='Vector provider to use to store the collection')

class ListVectorCollectionsConfig(Input):
    """List vector collections."""
    operation: Literal['list_vector_collections'] = Field('list_vector_collections', json_schema_extra={"ui:hidden": True})

class DeleteVectorCollectionConfig(Input):
    """Delete a vector collection or specific vectors."""
    operation: Literal['delete_vector_collection'] = Field('delete_vector_collection', json_schema_extra={"ui:hidden": True})
    collection_name: str = Field(...)
    delete_all: Optional[bool] = Field(None)
    ids: Optional[list[str]] = Field(None)
    filter: Optional[dict[str, Any]] = Field(None)

class UpsertVectorConfig(Input):
    """Update or insert a vector into a collection."""
    operation: Literal['upsert_vector'] = Field('upsert_vector', json_schema_extra={"ui:hidden": True})
    collection_name: str = Field(...)
    vector_id: str = Field(...)
    metatag: Optional[str] = Field(None)
    data: Optional[str] = Field(None)
    embedding: list[float] = Field(...)

class ListVectorIdsConfig(Input):
    """List vector IDs in a collection."""
    operation: Literal['list_vector_ids'] = Field('list_vector_ids', json_schema_extra={"ui:hidden": True})
    collection_name: str = Field(...)
    limit: Optional[int] = Field(None)
    prefix: Optional[str] = Field(None)
    pagination_token: Optional[str] = Field(None)

class GetVectorRecordConfig(Input):
    """Get a specific record in a vector collection."""
    operation: Literal['get_vector_record'] = Field('get_vector_record', json_schema_extra={"ui:hidden": True})
    collection_name: str = Field(...)
    ids: str = Field(...)

class QueryVectorsConfig(Input):
    """Query vectors in a collection."""
    operation: Literal['query_vectors'] = Field('query_vectors', json_schema_extra={"ui:hidden": True})
    collection_name: str = Field(...)
    vector: list[float] = Field(...)
    top_k: Optional[int] = Field(None)
    include_values: Optional[bool] = Field(None)
    include_metadata: Optional[bool] = Field(None)
    filter: Optional[dict[str, Any]] = Field(None)
    metatag: Optional[str] = Field(None)

class ProcessDocumentConfig(Input):
    """Process a document for RAG tuning."""
    operation: Literal['process_document'] = Field('process_document', json_schema_extra={"ui:hidden": True})
    collection_name: str = Field(...)
    url: str = Field(..., description='URL of the document to process. Supported file types: PDF, DOC, DOCX, TXT, CSV, XLS, XLSX')
    metatag: Optional[str] = Field(None, description='Optional metadata tag to associate with the document')
    vector_provider: Optional[Literal['pinecone', 'qdrant']] = Field(None, description='Vector provider to use to store the collection')

class ListRagCollectionsConfig(Input):
    """List collections for RAG tuning."""
    operation: Literal['list_rag_collections'] = Field('list_rag_collections', json_schema_extra={"ui:hidden": True})
    vector_provider: Optional[Literal['pinecone', 'qdrant']] = Field(None, description='Vector provider to fetch collections for')

ApipieAIConfig = Annotated[Union[CreateChatCompletionConfig, CreateEmbeddingConfig, GenerateImageConfig, GetStateConfig, UpdateStateConfig, DeleteStateConfig, ListQueriesConfig, ListModelsConfig, ListDetailedModelsConfig, CreateVectorCollectionConfig, ListVectorCollectionsConfig, DeleteVectorCollectionConfig, UpsertVectorConfig, ListVectorIdsConfig, GetVectorRecordConfig, QueryVectorsConfig, ProcessDocumentConfig, ListRagCollectionsConfig], Field(discriminator="operation")]

class ApipieAIFullConfig(NodeConfig[ApipieAIConfig, ApipieAICredential]):
    pass

ROUTES = {'create_chat_completion': ('POST', '/v1/chat/completions', []), 'create_embedding': ('POST', '/v1/embeddings', []), 'generate_image': ('POST', '/v1/images/generations', []), 'get_state': ('GET', '/v1/state', ['user', 'app_name']), 'update_state': ('POST', '/v1/state', ['app_name']), 'delete_state': ('DELETE', '/v1/state', ['user', 'app_name']), 'list_queries': ('GET', '/v1/queries/', ['limit', 'offset', 'show', 'days', 'user', 'app', 'provider', 'route']), 'list_models': ('GET', '/v1/models', ['type', 'subtype', 'provider', 'enabled']), 'list_detailed_models': ('GET', '/v1/models/detailed', ['type', 'provider', 'model']), 'create_vector_collection': ('POST', '/vectors', []), 'list_vector_collections': ('POST', '/vectors/listcollections', []), 'delete_vector_collection': ('POST', '/vectors/delete', []), 'upsert_vector': ('PUT', '/vectors/upsert', []), 'list_vector_ids': ('POST', '/vectors/list', []), 'get_vector_record': ('GET', '/vectors/fetch', ['collection_name', 'ids']), 'query_vectors': ('POST', '/vectors/query', []), 'process_document': ('POST', '/ragtune', []), 'list_rag_collections': ('POST', '/ragtune/listcollections', [])}

class ApipieAINode(WorkflowNode):
    integration_type = "automation-apipie-ai"
    connection_evidence = ConnectionEvidence(noun="APIpie app state", operation="get_state")

    @classmethod
    def get_config_model(cls):
        return ApipieAIFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an APIpie API key")
        op = self.config.config
        method, path, query_fields = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        params = {key: values.pop(key) for key in query_fields if key in values}
        if op.operation == "create_chat_completion":
            values["stream"] = False
        if op.operation == "generate_image":
            values["response_format"] = "url"
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://apipie.ai" + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key,
                         "Accept": "application/json"}, params=params,
                **({"json": values} if method in {"POST", "PUT"} else {}))
        if response.is_error:
            # Preserve the provider's rejection without allowing it to echo the secret.
            detail = response.text.replace(self.config.credentials.api_key, "[redacted]")[:2000]
            raise ValueError(f"APIpie HTTP {response.status_code}: {detail}")
        response.raise_for_status()
        # These two published operations have no response media/schema.
        if not response.content and op.operation in {"upsert_vector", "query_vectors"}:
            result = {"data": None, "http_status": response.status_code}
            await self.emit(result)
            return result
        body = response.json()
        if not isinstance(body, (dict, list)):
            raise ValueError("APIpie returned an unexpected JSON response")
        if isinstance(body, dict) and (body.get("error") or body.get("success") is False):
            raise ValueError("APIpie error: " + str(body).replace(self.config.credentials.api_key, "[redacted]")[:2000])
        result = {"data": body}
        await self.emit(result)
        return result

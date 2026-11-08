"""Automate Arize AX datasets, experiments and prompts with a pasted API key.

Each action makes one request to the published v2 API. Lists preserve the
provider's pagination envelope so callers can pass the next cursor explicitly.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, Json, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence, summarize_provider_text
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ArizeAxApiKey(BaseModel):
    model_config = ConfigDict(title="Arize AX API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://arize.com/docs/ax/security-and-settings/api-keys",
        "x-credential-instructions": "Create a user API key in Arize AX, then paste the key here without the Bearer prefix. Grant access to the spaces and resources your actions need. NoClick checks the key by listing accessible spaces.",
    })
    credential_type: Literal["arize_ax_api_key"] = Field("arize_ax_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not value or value in {".", ".."} or any(c.isspace() or ord(c) < 32 for c in value):
                raise ValueError("Use the opaque Arize resource ID")
        return value


class ListSpaces(_Input):
    """List spaces."""
    operation: Literal['list_spaces'] = Field('list_spaces', title='List spaces', json_schema_extra={"ui:hidden": True})
    org_id: str | None = Field(None, title='Org id', description='A universally unique identifier (base64-encoded opaque string).')
    name: Annotated[str, Field(max_length=255)] | None = Field(None, title='Name')
    limit: Annotated[int, Field(ge=1, le=100)] = Field(50, title='Limit')
    cursor: str | None = Field(None, title='Cursor')


class ListProjects(_Input):
    """List projects."""
    operation: Literal['list_projects'] = Field('list_projects', title='List projects', json_schema_extra={"ui:hidden": True})
    space_id: str | None = Field(None, title='Space id', description='A universally unique identifier (base64-encoded opaque string).')
    space_name: Annotated[str, Field(max_length=255)] | None = Field(None, title='Space name')
    name: Annotated[str, Field(max_length=255)] | None = Field(None, title='Name')
    limit: Annotated[int, Field(ge=1, le=100)] = Field(50, title='Limit')
    cursor: str | None = Field(None, title='Cursor')
    project_type: Literal['APPLICATION', 'HARNESS', 'EXPERIMENT'] | None = Field(None, title='Project type', description='The kind of LLM project.\n- `APPLICATION` — A user-facing LLM application project.\n- `HARNESS` — An agent harness session project.\n- `EXPERIMENT` — An experiment trace project.\n')


class GetProject(_Input):
    """Get a project."""
    operation: Literal['get_project'] = Field('get_project', title='Get a project', json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., title='Project id', description='A universally unique identifier (base64-encoded opaque string).')


class ListDatasets(_Input):
    """List datasets."""
    operation: Literal['list_datasets'] = Field('list_datasets', title='List datasets', json_schema_extra={"ui:hidden": True})
    space_id: str | None = Field(None, title='Space id', description='A universally unique identifier (base64-encoded opaque string).')
    space_name: Annotated[str, Field(max_length=255)] | None = Field(None, title='Space name')
    name: Annotated[str, Field(max_length=255)] | None = Field(None, title='Name')
    limit: Annotated[int, Field(ge=1, le=100)] = Field(50, title='Limit')
    cursor: str | None = Field(None, title='Cursor')


class CreateDataset(_Input):
    """Create a dataset."""
    operation: Literal['create_dataset'] = Field('create_dataset', title='Create a dataset', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name', description='Name of the new dataset. Must be unique within the space.')
    space_id: str = Field(..., title='Space id', description='ID of the space the dataset will belong to')
    examples: Json[Annotated[list[dict[str, Any]], Field(min_length=1, max_length=1000)]] = Field(..., title='Examples (JSON)', description='Array of examples for the new dataset', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})


class GetDataset(_Input):
    """Get a dataset."""
    operation: Literal['get_dataset'] = Field('get_dataset', title='Get a dataset', json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., title='Dataset id', description='A universally unique identifier (base64-encoded opaque string).')


class UpdateDataset(_Input):
    """Update a dataset."""
    operation: Literal['update_dataset'] = Field('update_dataset', title='Update a dataset', json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., title='Dataset id', description='A universally unique identifier (base64-encoded opaque string).')
    name: str = Field(..., title='Name', description='New name for the dataset. Must be unique within the space.')


class DeleteDataset(_Input):
    """Delete a dataset."""
    operation: Literal['delete_dataset'] = Field('delete_dataset', title='Delete a dataset', json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., title='Dataset id', description='A universally unique identifier (base64-encoded opaque string).')


class ListDatasetExamples(_Input):
    """List dataset examples."""
    operation: Literal['list_dataset_examples'] = Field('list_dataset_examples', title='List dataset examples', json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., title='Dataset id', description='A universally unique identifier (base64-encoded opaque string).')
    dataset_version_id: str | None = Field(None, title='Dataset version id', description='A universally unique identifier (base64-encoded opaque string).')
    limit: Annotated[int, Field(ge=1, le=500)] = Field(50, title='Limit')
    cursor: str | None = Field(None, title='Cursor')


class InsertDatasetExamples(_Input):
    """Add new examples to a dataset."""
    operation: Literal['insert_dataset_examples'] = Field('insert_dataset_examples', title='Add new examples to a dataset', json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., title='Dataset id', description='A universally unique identifier (base64-encoded opaque string).')
    dataset_version_id: str | None = Field(None, title='Dataset version id', description='A universally unique identifier (base64-encoded opaque string).')
    examples: Json[Annotated[list[dict[str, Any]], Field(min_length=1, max_length=1000)]] = Field(..., title='Examples (JSON)', description='Array of examples to append to the dataset version', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})


class UpdateDatasetExampleInput(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = Field(..., title='Id', description='System-assigned unique ID for the example')


class UpdateDatasetExamples(_Input):
    """Update existing examples in a dataset."""
    operation: Literal['update_dataset_examples'] = Field('update_dataset_examples', title='Update existing examples in a dataset', json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., title='Dataset id', description='A universally unique identifier (base64-encoded opaque string).')
    dataset_version_id: str | None = Field(None, title='Dataset version id', description='A universally unique identifier (base64-encoded opaque string).')
    examples: Json[Annotated[list[UpdateDatasetExampleInput], Field(min_length=1, max_length=1000)]] = Field(..., title='Examples (JSON)', description="Array of examples with 'id' field for matching and updating existing records", json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})
    new_version: str | None = Field(None, title='New version', description='Name for the new version. If provided (non-empty), creates a\nnew version with that name.\n\nIf omitted or empty, updates the existing version in-place.\n')


class DeleteDatasetExamples(_Input):
    """Delete dataset examples."""
    operation: Literal['delete_dataset_examples'] = Field('delete_dataset_examples', title='Delete dataset examples', json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., title='Dataset id', description='A universally unique identifier (base64-encoded opaque string).')
    dataset_version_id: str = Field(..., title='Dataset version id', description='Version to delete the examples from. Required. Examples are\nremoved in place from this version; no new version is created.\n')
    example_ids: Json[Annotated[list[str], Field(min_length=1, max_length=1000)]] = Field(..., title='Example ids (JSON)', description='IDs of the examples to delete. Up to 1000 per request.', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})


class ListExperiments(_Input):
    """List experiments."""
    operation: Literal['list_experiments'] = Field('list_experiments', title='List experiments', json_schema_extra={"ui:hidden": True})
    dataset_id: str | None = Field(None, title='Dataset id', description='A universally unique identifier (base64-encoded opaque string).')
    space_id: str | None = Field(None, title='Space id', description='A universally unique identifier (base64-encoded opaque string).')
    name: Annotated[str, Field(max_length=255)] | None = Field(None, title='Name')
    limit: Annotated[int, Field(ge=1, le=100)] = Field(50, title='Limit')
    cursor: str | None = Field(None, title='Cursor')


class ExperimentRunInput(BaseModel):
    model_config = ConfigDict(extra='allow')
    example_id: str | None = Field(None, title='Example id', description='ID of the dataset example associated with this experiment run. Provided when the experiment is associated with a dataset; omitted otherwise.')
    output: str = Field(..., title='Output', description='output of the task for the matching example')


class CreateExperiment(_Input):
    """Create an experiment."""
    operation: Literal['create_experiment'] = Field('create_experiment', title='Create an experiment', json_schema_extra={"ui:hidden": True})
    name: Annotated[str, Field(min_length=1, max_length=255, pattern='^[^"\\\\]*$')] = Field(..., title='Name', description='Name of the experiment. Must be 1–255 characters and must not contain\ndouble quotes (`"`) or backslashes (`\\`).\n')
    dataset_id: str | None = Field(None, title='Dataset id', description="ID of the dataset to associate the experiment with. Provide `space_id` instead when the experiment isn't associated with a dataset.")
    space_id: str | None = Field(None, title='Space id', description='ID of the space to create the experiment in. Provide instead of `dataset_id`.')
    experiment_runs: Json[Annotated[list[ExperimentRunInput], Field(min_length=1, max_length=1000)]] = Field(..., title='Experiment runs (JSON)', description='Array of experiment run data. Between 1 and 1000 runs per request.', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})

    @model_validator(mode="after")
    def target(self):
        if bool(self.dataset_id) == bool(self.space_id):
            raise ValueError("Provide exactly one of dataset_id or space_id")
        return self


class GetExperiment(_Input):
    """Get an experiment."""
    operation: Literal['get_experiment'] = Field('get_experiment', title='Get an experiment', json_schema_extra={"ui:hidden": True})
    experiment_id: str = Field(..., title='Experiment id', description='A universally unique identifier (base64-encoded opaque string).')


class DeleteExperiment(_Input):
    """Delete an experiment."""
    operation: Literal['delete_experiment'] = Field('delete_experiment', title='Delete an experiment', json_schema_extra={"ui:hidden": True})
    experiment_id: str = Field(..., title='Experiment id', description='A universally unique identifier (base64-encoded opaque string).')


class ListExperimentRuns(_Input):
    """List experiment runs."""
    operation: Literal['list_experiment_runs'] = Field('list_experiment_runs', title='List experiment runs', json_schema_extra={"ui:hidden": True})
    experiment_id: str = Field(..., title='Experiment id', description='A universally unique identifier (base64-encoded opaque string).')
    limit: Annotated[int, Field(ge=1, le=500)] = Field(50, title='Limit')
    cursor: str | None = Field(None, title='Cursor')


class InsertExperimentRuns(_Input):
    """Append runs to an experiment."""
    operation: Literal['insert_experiment_runs'] = Field('insert_experiment_runs', title='Append runs to an experiment', json_schema_extra={"ui:hidden": True})
    experiment_id: str = Field(..., title='Experiment id', description='A universally unique identifier (base64-encoded opaque string).')
    experiment_runs: Json[Annotated[list[ExperimentRunInput], Field(min_length=1, max_length=1000)]] = Field(..., title='Experiment runs (JSON)', description='Array of experiment run data to append to the experiment. Between 1 and 1000 runs per request.', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})


class ListPrompts(_Input):
    """List prompts."""
    operation: Literal['list_prompts'] = Field('list_prompts', title='List prompts', json_schema_extra={"ui:hidden": True})
    space_id: str | None = Field(None, title='Space id', description='A universally unique identifier (base64-encoded opaque string).')
    space_name: Annotated[str, Field(max_length=255)] | None = Field(None, title='Space name')
    name: Annotated[str, Field(max_length=255)] | None = Field(None, title='Name')
    limit: Annotated[int, Field(ge=1, le=100)] = Field(50, title='Limit')
    cursor: str | None = Field(None, title='Cursor')


class ToolCallFunctionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(..., title='Name', description='The name of the function')
    arguments: str = Field(..., title='Arguments', description='The arguments to the function as a JSON string')


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str | None = Field(None, title='Id', description='The ID of the tool call')
    type: Literal['FUNCTION'] = Field(..., title='Type', description='The type of tool call')
    function: ToolCallFunctionRequest = Field(..., title='Function', description='The function to call (strict request form of ToolCallFunction)')


class LLMMessageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['USER', 'ASSISTANT', 'SYSTEM', 'TOOL'] = Field(..., title='Role', description='The role of the message author')
    content: str | None = Field(None, title='Content', description='The content of the message')
    tool_call_id: str | None = Field(None, title='Tool call id', description='The ID of the tool call this message is responding to')
    tool_calls: list[ToolCallRequest] | None = Field(None, title='Tool calls', description='Tool calls generated by the model')


class JsonSchemaConfigRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(None, title='Name', description='The name of the JSON schema')
    description: str | None = Field(None, title='Description', description='A description of the JSON schema')
    schema_value: dict[str, Any] | None = Field(None, alias="schema", title='Schema', description='The JSON schema object')
    strict: bool = Field(False, title='Strict', description='Whether to enforce strict schema validation. Defaults to `false`.')


class ResponseFormatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['TEXT', 'JSON_OBJECT', 'JSON_SCHEMA'] = Field('TEXT', title='Type', description='The response format type. Defaults to `TEXT` if not specified.')
    json_schema: JsonSchemaConfigRequest | None = Field(None, title='Json schema', description='JSON schema configuration (when type is JSON_SCHEMA)')


class ToolConfigRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tools: list[dict[str, Any]] | None = Field(None, title='Tools', description='List of tool definitions available to the model')
    tool_choice: Any | None = Field(None, title='Tool choice', description='Tool choice configuration')


class InvocationParamsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    temperature: float | None = Field(None, title='Temperature', description='Sampling temperature (higher = more random)')
    max_tokens: int | None = Field(None, title='Max tokens', description='Maximum number of tokens to generate')
    max_completion_tokens: int | None = Field(None, title='Max completion tokens', description='Maximum number of completion tokens to generate')
    top_p: float | None = Field(None, title='Top p', description='Nucleus sampling parameter')
    frequency_penalty: float | None = Field(None, title='Frequency penalty', description='Frequency penalty (-2.0 to 2.0)')
    presence_penalty: float | None = Field(None, title='Presence penalty', description='Presence penalty (-2.0 to 2.0)')
    stop: list[str] | None = Field(None, title='Stop', description='Stop sequences')
    response_format: ResponseFormatRequest | None = Field(None, title='Response format', description="Response format configuration. Optional. When omitted, no structured output constraint is applied (the provider's default plain-text behavior is used).")
    tool_config: ToolConfigRequest | None = Field(None, title='Tool config', description='Tool configuration for the LLM invocation. Optional. When omitted, no tools are made available to the model.')
    top_k: int | None = Field(None, title='Top k', description='Top-K sampling parameter. A top-K of 1 means the next selected token is the most probable (greedy decoding).')
    thinking_level: str | None = Field(None, title='Thinking level', description="Controls how much reasoning the model performs before responding. Supported by Gemini 3.x models. Accepted values: 'low', 'high'.")
    thinking_budget: int | None = Field(None, title='Thinking budget', description='Maximum tokens the model may use for internal reasoning. Supported by Gemini 2.5 models. Range: 0-24576 (Flash/Flash-Lite) or 128-32768 (Pro). Set 0 to disable thinking on Flash models.')
    reasoning_effort: str | None = Field(None, title='Reasoning effort', description="Controls how much reasoning the model performs before responding. Supported by OpenAI o-series and GPT-5 models. o-series: 'low' | 'medium' | 'high'. GPT-5: 'none' | 'low' | 'medium' | 'high' | 'xhigh'.")
    verbosity: str | None = Field(None, title='Verbosity', description="Controls the verbosity of model output. Supported by OpenAI GPT-5 series. Accepted values: 'low' | 'medium' | 'high'.")


class AzureParamsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    azure_deployment_name: str | None = Field(None, title='Azure deployment name', description='The Azure deployment name')
    azure_openai_endpoint: str | None = Field(None, title='Azure openai endpoint', description='The Azure OpenAI endpoint URL')
    azure_openai_version: str | None = Field(None, title='Azure openai version', description='The Azure OpenAI API version')


class AnthropicHeadersRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    anthropic_beta: list[str | None] | None = Field(None, title='Anthropic beta', description='Anthropic beta feature flags')


class BedrockOptionsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    use_converse_endpoint: bool = Field(False, title='Use converse endpoint', description='Whether to use the AWS Bedrock Converse endpoint. Defaults to `false`.')


class ProviderParamsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    azure_params: AzureParamsRequest | None = Field(None, title='Azure params', description='Azure OpenAI specific parameters')
    anthropic_headers: AnthropicHeadersRequest | None = Field(None, title='Anthropic headers', description='Anthropic-specific headers')
    anthropic_version: str | None = Field(None, title='Anthropic version', description='Anthropic API version')
    bedrock_options: BedrockOptionsRequest | None = Field(None, title='Bedrock options', description='AWS Bedrock options')
    region: str | None = Field(None, title='Region', description='Region for the model deployment')


class PromptVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    commit_message: str = Field(..., title='Commit message', description='Commit message describing this version')
    input_variable_format: Literal['F_STRING', 'MUSTACHE', 'NONE'] = Field('F_STRING', title='Input variable format', description='Format for input variables in the prompt messages. Defaults to `F_STRING` if not provided.')
    provider: Literal['OPEN_AI', 'AZURE_OPEN_AI', 'AWS_BEDROCK', 'VERTEX_AI', 'ANTHROPIC', 'CUSTOM'] = Field(..., title='Provider', description='The LLM provider to use')
    model: str | None = Field(None, title='Model', description='The model to use for the call. Optional. If omitted, no default model is set on the prompt version.')
    messages: Annotated[list[LLMMessageRequest], Field(min_length=1)] = Field(..., title='Messages', description='The messages that make up the prompt template')
    invocation_params: InvocationParamsRequest | None = Field(None, title='Invocation params', description='Parameters for the LLM invocation in a write request (strict form of InvocationParams; leaf schemas use *Request variants)')
    provider_params: ProviderParamsRequest | None = Field(None, title='Provider params', description='Provider-specific parameters in a write request (strict form of ProviderParams; leaf schemas use *Request variants)')


class CreatePrompt(_Input):
    """Create a prompt."""
    operation: Literal['create_prompt'] = Field('create_prompt', title='Create a prompt', json_schema_extra={"ui:hidden": True})
    space_id: str = Field(..., title='Space id', description='ID of the space to create the prompt in')
    name: str = Field(..., title='Name', description='Name of the prompt (must be unique within the space)')
    description: str | None = Field(None, title='Description', description='Description of the prompt. Optional. If omitted, the prompt has no description.')
    version: Json[PromptVersionCreateRequest] = Field(..., title='Version (JSON)', description='Initial version configuration for a new prompt', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})


class GetPrompt(_Input):
    """Get a prompt."""
    operation: Literal['get_prompt'] = Field('get_prompt', title='Get a prompt', json_schema_extra={"ui:hidden": True})
    prompt_id: str = Field(..., title='Prompt id', description='A universally unique identifier (base64-encoded opaque string).')
    version_id: str | None = Field(None, title='Version id', description='A universally unique identifier (base64-encoded opaque string).')
    label: str | None = Field(None, title='Label')

    @model_validator(mode="after")
    def version_selector(self):
        if self.version_id is not None and self.label is not None:
            raise ValueError("Use version_id or label, not both")
        return self


class UpdatePrompt(_Input):
    """Update a prompt."""
    operation: Literal['update_prompt'] = Field('update_prompt', title='Update a prompt', json_schema_extra={"ui:hidden": True})
    prompt_id: str = Field(..., title='Prompt id', description='A universally unique identifier (base64-encoded opaque string).')
    description: str | None = Field(..., title='Description', description='Updated description for the prompt')


class DeletePrompt(_Input):
    """Delete a prompt."""
    operation: Literal['delete_prompt'] = Field('delete_prompt', title='Delete a prompt', json_schema_extra={"ui:hidden": True})
    prompt_id: str = Field(..., title='Prompt id', description='A universally unique identifier (base64-encoded opaque string).')


class ListPromptVersions(_Input):
    """List prompt versions."""
    operation: Literal['list_prompt_versions'] = Field('list_prompt_versions', title='List prompt versions', json_schema_extra={"ui:hidden": True})
    prompt_id: str = Field(..., title='Prompt id', description='A universally unique identifier (base64-encoded opaque string).')
    limit: Annotated[int, Field(ge=1, le=100)] = Field(50, title='Limit')
    cursor: str | None = Field(None, title='Cursor')


class CreatePromptVersion(_Input):
    """Create a prompt version."""
    operation: Literal['create_prompt_version'] = Field('create_prompt_version', title='Create a prompt version', json_schema_extra={"ui:hidden": True})
    prompt_id: str = Field(..., title='Prompt id', description='A universally unique identifier (base64-encoded opaque string).')
    commit_message: str = Field(..., title='Commit message', description='Commit message describing this version')
    input_variable_format: Literal['F_STRING', 'MUSTACHE', 'NONE'] | None = Field(None, title='Input variable format', description='The format for input variables in the prompt messages. Defaults to `F_STRING` if not provided.\n- `F_STRING`: Single curly braces ({variable_name})\n- `MUSTACHE`: Double curly braces ({{variable_name}})\n- `NONE`: **Deprecated.** Treated as `F_STRING`. Will be removed in a future version.\n')
    provider: Literal['OPEN_AI', 'AZURE_OPEN_AI', 'AWS_BEDROCK', 'VERTEX_AI', 'ANTHROPIC', 'CUSTOM'] = Field(..., title='Provider', description='The LLM provider to use')
    model: str | None = Field(None, title='Model', description='The model to use for the call. Optional. If omitted, no default model is set on the version.')
    messages: Json[Annotated[list[LLMMessageRequest], Field(min_length=1)]] = Field(..., title='Messages (JSON)', description='The messages that make up the prompt template', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})
    invocation_params: Json[InvocationParamsRequest] | None = Field(None, title='Invocation params (JSON)', description='Parameters for the LLM invocation in a write request (strict form of InvocationParams; leaf schemas use *Request variants)', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})
    provider_params: Json[ProviderParamsRequest] | None = Field(None, title='Provider params (JSON)', description='Provider-specific parameters in a write request (strict form of ProviderParams; leaf schemas use *Request variants)', json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})


ArizeAxOperation = Annotated[Union[
    ListSpaces, ListProjects, GetProject, ListDatasets, CreateDataset, GetDataset, UpdateDataset, DeleteDataset, ListDatasetExamples, InsertDatasetExamples, UpdateDatasetExamples, DeleteDatasetExamples, ListExperiments, CreateExperiment, GetExperiment, DeleteExperiment, ListExperimentRuns, InsertExperimentRuns, ListPrompts, CreatePrompt, GetPrompt, UpdatePrompt, DeletePrompt, ListPromptVersions, CreatePromptVersion
], Field(discriminator="operation")]


class ArizeAxNodeConfig(NodeConfig[ArizeAxOperation, ArizeAxApiKey]):
    pass


ROUTES = {'list_spaces': ('GET', '/v2/spaces'),
 'list_projects': ('GET', '/v2/projects'),
 'get_project': ('GET', '/v2/projects/{project_id}'),
 'list_datasets': ('GET', '/v2/datasets'),
 'create_dataset': ('POST', '/v2/datasets'),
 'get_dataset': ('GET', '/v2/datasets/{dataset_id}'),
 'update_dataset': ('PATCH', '/v2/datasets/{dataset_id}'),
 'delete_dataset': ('DELETE', '/v2/datasets/{dataset_id}'),
 'list_dataset_examples': ('GET', '/v2/datasets/{dataset_id}/examples'),
 'insert_dataset_examples': ('POST', '/v2/datasets/{dataset_id}/examples'),
 'update_dataset_examples': ('PATCH', '/v2/datasets/{dataset_id}/examples'),
 'delete_dataset_examples': ('DELETE', '/v2/datasets/{dataset_id}/examples'),
 'list_experiments': ('GET', '/v2/experiments'),
 'create_experiment': ('POST', '/v2/experiments'),
 'get_experiment': ('GET', '/v2/experiments/{experiment_id}'),
 'delete_experiment': ('DELETE', '/v2/experiments/{experiment_id}'),
 'list_experiment_runs': ('GET', '/v2/experiments/{experiment_id}/runs'),
 'insert_experiment_runs': ('POST', '/v2/experiments/{experiment_id}/runs'),
 'list_prompts': ('GET', '/v2/prompts'),
 'create_prompt': ('POST', '/v2/prompts'),
 'get_prompt': ('GET', '/v2/prompts/{prompt_id}'),
 'update_prompt': ('PATCH', '/v2/prompts/{prompt_id}'),
 'delete_prompt': ('DELETE', '/v2/prompts/{prompt_id}'),
 'list_prompt_versions': ('GET', '/v2/prompts/{prompt_id}/versions'),
 'create_prompt_version': ('POST', '/v2/prompts/{prompt_id}/versions')}

PARAMETERS = {'list_spaces': [('org_id', 'query'), ('name', 'query'), ('limit', 'query'), ('cursor', 'query')],
 'list_projects': [('space_id', 'query'),
                   ('space_name', 'query'),
                   ('name', 'query'),
                   ('limit', 'query'),
                   ('cursor', 'query'),
                   ('project_type', 'query')],
 'get_project': [('project_id', 'path')],
 'list_datasets': [('space_id', 'query'),
                   ('space_name', 'query'),
                   ('name', 'query'),
                   ('limit', 'query'),
                   ('cursor', 'query')],
 'create_dataset': [],
 'get_dataset': [('dataset_id', 'path')],
 'update_dataset': [('dataset_id', 'path')],
 'delete_dataset': [('dataset_id', 'path')],
 'list_dataset_examples': [('dataset_id', 'path'),
                           ('dataset_version_id', 'query'),
                           ('limit', 'query'),
                           ('cursor', 'query')],
 'insert_dataset_examples': [('dataset_id', 'path'), ('dataset_version_id', 'query')],
 'update_dataset_examples': [('dataset_id', 'path'), ('dataset_version_id', 'query')],
 'delete_dataset_examples': [('dataset_id', 'path')],
 'list_experiments': [('dataset_id', 'query'),
                      ('space_id', 'query'),
                      ('name', 'query'),
                      ('limit', 'query'),
                      ('cursor', 'query')],
 'create_experiment': [],
 'get_experiment': [('experiment_id', 'path')],
 'delete_experiment': [('experiment_id', 'path')],
 'list_experiment_runs': [('experiment_id', 'path'), ('limit', 'query'), ('cursor', 'query')],
 'insert_experiment_runs': [('experiment_id', 'path')],
 'list_prompts': [('space_id', 'query'),
                  ('space_name', 'query'),
                  ('name', 'query'),
                  ('limit', 'query'),
                  ('cursor', 'query')],
 'create_prompt': [],
 'get_prompt': [('prompt_id', 'path'), ('version_id', 'query'), ('label', 'query')],
 'update_prompt': [('prompt_id', 'path')],
 'delete_prompt': [('prompt_id', 'path')],
 'list_prompt_versions': [('prompt_id', 'path'), ('limit', 'query'), ('cursor', 'query')],
 'create_prompt_version': [('prompt_id', 'path')]}


LIST_KEYS = {
    "list_spaces": "spaces", "list_projects": "projects", "list_datasets": "datasets",
    "list_dataset_examples": "examples", "list_experiments": "experiments",
    "list_experiment_runs": "experiment_runs", "list_prompts": "prompts",
    "list_prompt_versions": "prompt_versions",
}


class ArizeAxNode(WorkflowNode):
    integration_type = "automation-arize-ax"
    connection_evidence = ConnectionEvidence(noun="spaces", operation="list_spaces")

    @classmethod
    def get_config_model(cls):
        return ArizeAxNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Arize AX API key")
        config = self.config.config
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude_unset=True, exclude_none=True, by_alias=True)
        parameters = PARAMETERS[config.operation]
        path = route.format(**{name: quote(str(getattr(config, name)), safe="")
            for name, location in parameters if location == "path"})
        query = {name: getattr(config, name) for name, location in parameters
            if location == "query" and getattr(config, name) is not None}
        body = {name: value for name, value in values.items()
            if name != "operation" and name not in {key for key, _ in parameters}}
        if isinstance(config, UpdatePrompt):
            body["description"] = config.description
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, "https://api.arize.com" + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                params=query, **({"json": body} if body else {}))
        if not 200 <= response.status_code < 300:
            message = summarize_provider_text(response.text.replace(key, "[redacted]"), response.status_code)
            raise ValueError(f"Arize AX (HTTP {response.status_code}): {message}")
        if response.status_code == 204:
            return {"success": True, "http_status": 204}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Arize AX returned an invalid JSON object")
        if data.get("error") or data.get("errors"):
            message = summarize_provider_text(str(data.get("error") or data["errors"]).replace(key, "[redacted]"), response.status_code)
            raise ValueError(message)
        list_key = LIST_KEYS.get(config.operation)
        if list_key:
            if not isinstance(data.get(list_key), list) or not isinstance(data.get("pagination"), dict):
                raise ValueError("Arize AX returned an invalid list envelope")
            return {**data, "data": data[list_key]}
        return data

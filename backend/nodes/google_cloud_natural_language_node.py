"""Google Cloud Natural Language v1 document analysis.

Contract: https://language.googleapis.com/$discovery/rest?version=v1
API-key authentication: https://cloud.google.com/docs/authentication/api-keys-use
Analysis calls do not persist documents, but consume the project's paid quota.
There are no account resources, list methods, webhook registrations or events.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

API_BASE = "https://language.googleapis.com/v1"


def operation(name, label, category="Document Analysis"):
    return Field(name, title=label, json_schema_extra={
        "ui:hidden": True, "x-display-name": label, "x-category": category,
        "x-is-trigger": False,
    })


class GoogleCloudNaturalLanguageAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Google Cloud Natural Language API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "api_key",
            "x-credential-url": "https://console.cloud.google.com/apis/credentials",
            "x-credential-instructions": "Enable the Cloud Natural Language API and billing on your Google Cloud project, then paste an API key allowed to call this API. NoClick sends it in the x-goog-api-key header. Connecting analyzes the fixed text 'Hello, world!' and consumes analysis quota. This proves key acceptance, not account identity. With an API key, Cloud Storage documents must be publicly readable; private objects need an authenticated principal."})
    credential_type: Literal["google_cloud_natural_language_api_key"] = Field(
        "google_cloud_natural_language_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1,
        json_schema_extra={"ui:widget": "password", "ui:help": "Paste the key string from your Google Cloud project's Credentials page."})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without headers or spaces")
        return value


class _DocumentOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: Literal["PLAIN_TEXT", "HTML"] = Field("PLAIN_TEXT", title="Document Type")
    language: str | None = Field(None, title="Language", min_length=1,
        description="Optional ISO or BCP-47 code, such as en. Leave empty to detect the language. Supported languages vary by analysis method.")


class _Text(_DocumentOptions):
    content: str = Field(..., title="Text", min_length=1,
        description="Document text or HTML to analyze.", json_schema_extra={"ui:widget": "textarea"})


class _Storage(_DocumentOptions):
    gcs_content_uri: str = Field(..., title="Cloud Storage URI", min_length=1,
        description="gs://bucket/object path to a publicly readable text or HTML object. Object versioning is unsupported. NoClick sends the URI to Google without downloading it.")

    @field_validator("gcs_content_uri")
    @classmethod
    def uri(cls, value):
        if not re.fullmatch(r"gs://[a-z0-9][a-z0-9._-]+/[^\r\n?#]+", value):
            raise ValueError("Use a gs://bucket/object URI without a version or query")
        return value


class _Encoding(BaseModel):
    encoding_type: Literal["NONE", "UTF8", "UTF16", "UTF32"] = Field("UTF8", title="Offset Encoding",
        description="Encoding used to calculate token, entity and sentence offsets.")


class _Classification(BaseModel):
    classification_model: Literal["v1", "v2"] = Field("v2", title="Classification Model",
        description="v1 requires at least 20 words. v2 supports shorter documents and a larger category taxonomy.")


class _Features(BaseModel):
    extract_document_sentiment: bool = Field(True, title="Document Sentiment")
    extract_entities: bool = Field(True, title="Entities")
    extract_syntax: bool = Field(True, title="Syntax")
    extract_entity_sentiment: bool = Field(False, title="Entity Sentiment")
    classify_text: bool = Field(False, title="Classify Text")
    moderate_text: bool = Field(False, title="Moderate Text")
    classification_model: Literal["v1", "v2"] = Field("v2", title="Classification Model")

    @model_validator(mode="after")
    def enabled(self):
        if not any(getattr(self, field) for field in FEATURE_FIELDS):
            raise ValueError("Enable at least one analysis feature")
        return self


FEATURE_FIELDS = {
    "extract_document_sentiment": "extractDocumentSentiment", "extract_entities": "extractEntities",
    "extract_syntax": "extractSyntax", "extract_entity_sentiment": "extractEntitySentiment",
    "classify_text": "classifyText", "moderate_text": "moderateText",
}


class CheckConnection(BaseModel):
    operation: Literal["check_connection"] = operation("check_connection", "Check API Key", "Connection")


class AnalyzeSentimentText(_Text, _Encoding):
    operation: Literal["analyze_sentiment"] = operation("analyze_sentiment", "Analyze Sentiment")


class AnalyzeSentimentStorage(_Storage, _Encoding):
    operation: Literal["analyze_sentiment_from_storage"] = operation("analyze_sentiment_from_storage", "Analyze Sentiment from Cloud Storage")


class AnalyzeEntitiesText(_Text, _Encoding):
    operation: Literal["analyze_entities"] = operation("analyze_entities", "Analyze Entities")


class AnalyzeEntitiesStorage(_Storage, _Encoding):
    operation: Literal["analyze_entities_from_storage"] = operation("analyze_entities_from_storage", "Analyze Entities from Cloud Storage")


class AnalyzeEntitySentimentText(_Text, _Encoding):
    operation: Literal["analyze_entity_sentiment"] = operation("analyze_entity_sentiment", "Analyze Entity Sentiment")


class AnalyzeEntitySentimentStorage(_Storage, _Encoding):
    operation: Literal["analyze_entity_sentiment_from_storage"] = operation("analyze_entity_sentiment_from_storage", "Analyze Entity Sentiment from Cloud Storage")


class ClassifyTextText(_Text, _Classification):
    operation: Literal["classify_text"] = operation("classify_text", "Classify Text")


class ClassifyTextStorage(_Storage, _Classification):
    operation: Literal["classify_text_from_storage"] = operation("classify_text_from_storage", "Classify Text from Cloud Storage")


class ModerateTextText(_Text):
    operation: Literal["moderate_text"] = operation("moderate_text", "Moderate Text")


class ModerateTextStorage(_Storage):
    operation: Literal["moderate_text_from_storage"] = operation("moderate_text_from_storage", "Moderate Text from Cloud Storage")


class AnalyzeSyntaxText(_Text, _Encoding):
    operation: Literal["analyze_syntax"] = operation("analyze_syntax", "Analyze Syntax")


class AnalyzeSyntaxStorage(_Storage, _Encoding):
    operation: Literal["analyze_syntax_from_storage"] = operation("analyze_syntax_from_storage", "Analyze Syntax from Cloud Storage")


class AnnotateTextText(_Text, _Encoding, _Features):
    operation: Literal["annotate_text"] = operation("annotate_text", "Annotate Text")


class AnnotateTextStorage(_Storage, _Encoding, _Features):
    operation: Literal["annotate_text_from_storage"] = operation("annotate_text_from_storage", "Annotate Text from Cloud Storage")


GoogleCloudNaturalLanguageConfig = Annotated[Union[
    CheckConnection,
    AnalyzeSentimentText,
    AnalyzeSentimentStorage,
    AnalyzeEntitiesText,
    AnalyzeEntitiesStorage,
    AnalyzeEntitySentimentText,
    AnalyzeEntitySentimentStorage,
    ClassifyTextText,
    ClassifyTextStorage,
    ModerateTextText,
    ModerateTextStorage,
    AnalyzeSyntaxText,
    AnalyzeSyntaxStorage,
    AnnotateTextText,
    AnnotateTextStorage
], Field(discriminator="operation")]


class GoogleCloudNaturalLanguageNodeConfig(NodeConfig[GoogleCloudNaturalLanguageConfig, GoogleCloudNaturalLanguageAPIKeyCredential]):
    pass


ROUTES = {
    "analyze_sentiment": "analyzeSentiment",
    "analyze_entities": "analyzeEntities",
    "analyze_entity_sentiment": "analyzeEntitySentiment",
    "classify_text": "classifyText",
    "moderate_text": "moderateText",
    "analyze_syntax": "analyzeSyntax",
    "annotate_text": "annotateText",
}


class GoogleCloudNaturalLanguageNode(WorkflowNode):
    integration_type = "automation-google-cloud-natural-language"
    connection_evidence = ConnectionEvidence(operation="check_connection",
        noun="Natural Language API key acceptance", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return GoogleCloudNaturalLanguageNodeConfig

    async def execute(self, inputs):
        if not isinstance(self.config, GoogleCloudNaturalLanguageNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Google Cloud Natural Language API key")
        config = self.config.config
        action = config.operation
        if action == "check_connection":
            route = "analyzeSentiment"
            body = {"document": {"type": "PLAIN_TEXT", "content": "Hello, world!"}}
        else:
            name = action.removesuffix("_from_storage")
            route = ROUTES[name]
            document = {"type": config.document_type}
            if action.endswith("_from_storage"):
                document["gcsContentUri"] = config.gcs_content_uri
            else:
                document["content"] = config.content
            if config.language:
                document["language"] = config.language
            body = {"document": document}
            if isinstance(config, _Encoding):
                body["encodingType"] = config.encoding_type
            if isinstance(config, _Classification):
                body["classificationModelOptions"] = {config.classification_model + "Model": {}}
            if isinstance(config, _Features):
                body["features"] = {wire: getattr(config, field) for field, wire in FEATURE_FIELDS.items()}
                if config.classify_text:
                    body["features"]["classificationModelOptions"] = {config.classification_model + "Model": {}}
        key = self.config.credentials.api_key
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
                response = await client.request("POST", f"{API_BASE}/documents:{route}",
                    headers={"x-goog-api-key": key, "Accept": "application/json"}, json=body)
            if not 200 <= response.status_code < 300:
                try:
                    detail = response.json().get("error", {}).get("message")
                except (ValueError, AttributeError):
                    detail = None
                return {"status": "error", "status_code": response.status_code,
                    "error": (detail if isinstance(detail, str) else "Google did not confirm this analysis").replace(key, "[redacted]")}
            data = response.json()
            if not isinstance(data, dict) or "error" in data:
                return {"status": "error", "error": "Google returned an unexpected analysis response"}
            return {"status": "success", "operation": action, "data": data}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "Could not complete Google Cloud Natural Language analysis"}

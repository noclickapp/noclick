"""Rosette cloud text analytics using the published Babel Street v1 contract.

Each action makes one request, with no retry of billable analysis calls. The
on-premise-only gazetteer mutation is outside this cloud API integration.
Contract: https://developer.babelstreet.com/swagger.yaml (info.version 1.0).
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE_URL = "https://api.rosette.com/rest/v1"
CREDENTIAL_TYPE = "rosette_text_analytics_api_key"


class RosetteTextAnalyticsApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Rosette Text Analytics API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.babelstreet.com/",
            "x-credential-instructions": "Paste your Rosette API key from the Babel Street Analytics developer portal. NoClick sends it only to api.rosette.com using X-RosetteAPI-Key. The supported-language read verifies API reachability, not account identity. Analysis calls may consume your provider quota.",
        })
    credential_type: Literal["rosette_text_analytics_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _RosetteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)


class _RosetteDocument(_RosetteInput):
    content: str = Field(..., min_length=1, max_length=50000, title="Text", description="Text to analyze, up to the provider's 50,000-character limit.", json_schema_extra={"ui:widget": "textarea"})
    language: str | None = Field(None, pattern=r"^[a-z]{3}$", title="Language", description="Optional ISO 639-3 code, such as eng. Omit to let the service detect it.")


class RosetteDetectLanguage(_RosetteDocument):
    operation: Literal["detect_language"] = Field("detect_language", title="Detect Language", json_schema_extra={"ui:hidden": True})


class RosetteExtractEntities(_RosetteDocument):
    operation: Literal["extract_entities"] = Field("extract_entities", title="Extract Entities", json_schema_extra={"ui:hidden": True})


class RosetteCategorizeText(_RosetteDocument):
    operation: Literal["categorize_text"] = Field("categorize_text", title="Categorize Text", json_schema_extra={"ui:hidden": True})


class RosetteExtractEvents(_RosetteDocument):
    operation: Literal["extract_events"] = Field("extract_events", title="Extract Events", json_schema_extra={"ui:hidden": True})


class RosetteAnalyzeMorphology(_RosetteDocument):
    operation: Literal["analyze_morphology"] = Field("analyze_morphology", title="Analyze Morphology", json_schema_extra={"ui:hidden": True})
    morpho_feature: Literal["complete", "lemmas", "parts-of-speech", "compound-components", "han-readings"] = Field("complete", title="Morphological Feature")


class RosetteExtractRelationships(_RosetteDocument):
    operation: Literal["extract_relationships"] = Field("extract_relationships", title="Extract Relationships", json_schema_extra={"ui:hidden": True})


class RosetteFindSimilarTerms(_RosetteDocument):
    operation: Literal["find_similar_terms"] = Field("find_similar_terms", title="Find Similar Terms", json_schema_extra={"ui:hidden": True})
    result_languages: list[str] = Field(default_factory=lambda: ["eng"], min_length=1, max_length=20, title="Result Languages", description="ISO 639-3 language codes.")
    count: int = Field(10, ge=1, le=100, strict=True, title="Terms Per Language")

    @field_validator("result_languages")
    @classmethod
    def languages(cls, values):
        import re
        if any(not re.fullmatch(r"[a-z]{3}", value) for value in values):
            raise ValueError("Use ISO 639-3 language codes")
        return values


class RosetteCreateEmbeddings(_RosetteDocument):
    operation: Literal["create_embeddings"] = Field("create_embeddings", title="Create Embeddings", json_schema_extra={"ui:hidden": True})


class RosetteSplitSentences(_RosetteDocument):
    operation: Literal["split_sentences"] = Field("split_sentences", title="Split Sentences", json_schema_extra={"ui:hidden": True})


class RosetteAnalyzeSentiment(_RosetteDocument):
    operation: Literal["analyze_sentiment"] = Field("analyze_sentiment", title="Analyze Sentiment", json_schema_extra={"ui:hidden": True})


class RosetteParseDependencies(_RosetteDocument):
    operation: Literal["parse_dependencies"] = Field("parse_dependencies", title="Parse Dependencies", json_schema_extra={"ui:hidden": True})


class RosetteTokenizeText(_RosetteDocument):
    operation: Literal["tokenize_text"] = Field("tokenize_text", title="Tokenize Text", json_schema_extra={"ui:hidden": True})


class RosetteExtractTopics(_RosetteDocument):
    operation: Literal["extract_topics"] = Field("extract_topics", title="Extract Topics", json_schema_extra={"ui:hidden": True})


class RosetteTransliterateText(_RosetteDocument):
    operation: Literal["transliterate_text"] = Field("transliterate_text", title="Transliterate Text", json_schema_extra={"ui:hidden": True})


class RosetteName(_RosetteInput):
    text: str = Field(..., min_length=1, max_length=500)
    entity_type: Literal["PERSON", "LOCATION", "ORGANIZATION"] | None = Field(None, alias="entityType")
    language: str | None = Field(None, pattern=r"^[a-z]{3}$")
    script: str | None = Field(None, pattern=r"^[A-Z][a-z]{3}$")


class RosetteCompareNames(_RosetteInput):
    operation: Literal["compare_names"] = Field("compare_names", title="Compare Names", json_schema_extra={"ui:hidden": True})
    name1: RosetteName
    name2: RosetteName


class RosetteDeduplicateNames(_RosetteInput):
    operation: Literal["deduplicate_names"] = Field("deduplicate_names", title="Deduplicate Names", json_schema_extra={"ui:hidden": True})
    names: list[RosetteName] = Field(..., min_length=1, max_length=1000)
    threshold: float = Field(0.8, ge=0, le=1, allow_inf_nan=False)


class RosetteTranslateName(_RosetteInput):
    operation: Literal["translate_name"] = Field("translate_name", title="Translate Name", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    target_language: str = Field(..., pattern=r"^[a-z]{3}$", alias="targetLanguage")
    maximum_results: int = Field(1, ge=1, le=100, strict=True, alias="maximumResults")
    entity_type: Literal["PERSON", "LOCATION", "ORGANIZATION"] | None = Field(None, alias="entityType")


class RosetteCompareAddresses(_RosetteInput):
    operation: Literal["compare_addresses"] = Field("compare_addresses", title="Compare Addresses", json_schema_extra={"ui:hidden": True})
    address1: str = Field(..., min_length=1, max_length=5000)
    address2: str = Field(..., min_length=1, max_length=5000)


class RosetteGetServiceInfo(_RosetteInput):
    operation: Literal["get_service_info"] = Field("get_service_info", title="Get Service Info", json_schema_extra={"ui:hidden": True})


class RosetteGetEntityTypes(_RosetteInput):
    operation: Literal["get_entity_types"] = Field("get_entity_types", title="Get Entity Types", json_schema_extra={"ui:hidden": True})
    per_subsource_supported_entity_types: bool | None = Field(None, title="Include Entity Types by Subsource")


class RosetteGetEventSchemas(_RosetteInput):
    operation: Literal["get_event_schemas"] = Field("get_event_schemas", title="Get Event Schemas", json_schema_extra={"ui:hidden": True})


class RosetteListSupportedLanguages(_RosetteInput):
    operation: Literal["list_supported_languages"] = Field("list_supported_languages", title="List Supported Languages", description="Includes licensing flags. Used as a reachability check; does not identify an account.", json_schema_extra={"ui:hidden": True})


RosetteOperation = Annotated[Union[
    RosetteDetectLanguage,
    RosetteExtractEntities,
    RosetteCategorizeText,
    RosetteExtractEvents,
    RosetteAnalyzeMorphology,
    RosetteExtractRelationships,
    RosetteFindSimilarTerms,
    RosetteCreateEmbeddings,
    RosetteSplitSentences,
    RosetteAnalyzeSentiment,
    RosetteParseDependencies,
    RosetteTokenizeText,
    RosetteExtractTopics,
    RosetteTransliterateText,
    RosetteCompareNames,
    RosetteDeduplicateNames,
    RosetteTranslateName,
    RosetteCompareAddresses,
    RosetteGetServiceInfo,
    RosetteGetEntityTypes,
    RosetteGetEventSchemas,
    RosetteListSupportedLanguages
], Field(discriminator="operation")]


class RosetteTextAnalyticsConfig(NodeConfig[RosetteOperation, RosetteTextAnalyticsApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Fixed routes: user text and provider responses never select a destination.
ROUTES = {
    "detect_language": ("POST", "/language"),
    "extract_entities": ("POST", "/entities"),
    "categorize_text": ("POST", "/categories"),
    "extract_events": ("POST", "/events"),
    "analyze_morphology": ("POST", "/morphology/{morphoFeature}"),
    "extract_relationships": ("POST", "/relationships"),
    "find_similar_terms": ("POST", "/semantics/similar"),
    "create_embeddings": ("POST", "/semantics/vector"),
    "split_sentences": ("POST", "/sentences"),
    "analyze_sentiment": ("POST", "/sentiment"),
    "parse_dependencies": ("POST", "/syntax/dependencies"),
    "tokenize_text": ("POST", "/tokens"),
    "extract_topics": ("POST", "/topics"),
    "transliterate_text": ("POST", "/transliteration"),
    "compare_names": ("POST", "/name-similarity"),
    "deduplicate_names": ("POST", "/name-deduplication"),
    "translate_name": ("POST", "/name-translation"),
    "compare_addresses": ("POST", "/address-similarity"),
    "get_service_info": ("GET", "/info"),
    "get_entity_types": ("GET", "/entities/info"),
    "get_event_schemas": ("GET", "/events/info"),
    "list_supported_languages": ("GET", "/language/supported-languages"),
}


class _RosetteError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class RosetteTextAnalyticsNode(WorkflowNode):
    integration_type = "automation-rosette-text-analytics"
    connection_evidence = ConnectionEvidence(noun="Rosette API language availability", operation="list_supported_languages", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return RosetteTextAnalyticsConfig

    async def execute(self, inputs):
        if not isinstance(self.config, RosetteTextAnalyticsConfig) or self.config.credentials is None:
            raise ValueError("Connect a Rosette Text Analytics API key")
        config, credential = self.config.config, self.config.credentials
        method, path = ROUTES[config.operation]
        params = {}
        body = None
        if method == "POST":
            body = config.model_dump(exclude={"operation"}, exclude_none=True, by_alias=True)
            if isinstance(config, RosetteAnalyzeMorphology):
                path = path.replace("{morphoFeature}", body.pop("morpho_feature"))
            if isinstance(config, RosetteFindSimilarTerms):
                # The provider's own example uses strings here; LanguageCode's
                # object items contradict that example in the published spec.
                body["options"] = {"resultLanguages": body.pop("result_languages"), "count": body.pop("count")}
            encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(encoded) > 600000:
                raise ValueError("Rosette request exceeds the provider's 600 KB payload limit")
        elif isinstance(config, RosetteGetEntityTypes) and config.per_subsource_supported_entity_types is not None:
            params["perSubsourceSupportedEntityTypes"] = str(config.per_subsource_supported_entity_types).lower()
        try:
            payload = await self._request(method, path, params, body, credential.api_key)
            return {"status": "success", "operation": config.operation, "data": payload}
        except _RosetteError as exc:
            return {"status": "error", "operation": config.operation, "http_status": exc.status, "error": str(exc)}
        except (httpx.HTTPError, SSRFError, OSError):
            return {"status": "error", "operation": config.operation, "error": "Rosette request did not complete. Check provider usage before retrying a billable analysis."}

    async def _request(self, method, path, params, body, api_key):
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, BASE_URL + path, params=params,
                headers={"X-RosetteAPI-Key": api_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {})) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 10000000:
                        raise _RosetteError(response.status_code, "Rosette response exceeds the supported 10 MB size")
                if response.status_code != 200:
                    message = "Rosette returned HTTP " + str(response.status_code)
                    try:
                        error = json.loads(raw)
                        if isinstance(error, dict) and isinstance(error.get("message"), str):
                            # Preserve provider rejection text for connect, without
                            # reflecting an accidentally echoed credential.
                            message = error["message"].replace(api_key, "[redacted]")[:2000]
                    except (ValueError, UnicodeError):
                        pass
                    raise _RosetteError(response.status_code, message)
                media = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
                if media != "application/json":
                    raise _RosetteError(200, "Rosette did not return JSON")
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    raise _RosetteError(200, "Rosette returned invalid JSON") from None
                if not isinstance(payload, dict) or payload.get("error") or payload.get("code"):
                    raise _RosetteError(200, "Rosette returned an unexpected response envelope")
                return payload

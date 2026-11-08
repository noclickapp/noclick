"""Namsor v2 operations pinned to the provider's OpenAPI 2.1.4 contract.

Classifications are probabilistic estimates, not verified personal attributes.
Batch requests process at most 100 names and may consume paid provider units.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://v2.namsor.com/NamSorAPIv2"


class NamsorAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Namsor API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://v2.namsor.com/NamSorAPIv2/sign-in.html",
            "x-credential-instructions": "Paste your Namsor API key without a header prefix. NoClick reads your API key information to verify the connection. Classification requests consume your provider's API units; batch requests accept up to 100 names.",
        })
    credential_type: Literal["namsor_api_key"] = Field("namsor_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Namsor API key as text")
        value = clean_secret(value, field_name="API key", key=True)
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Text = Annotated[str, Field(min_length=1, max_length=1000)]
Country = Annotated[str, Field(pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2 country code.")]


class PersonalName(_Input):
    name: Text
    id: str | None = Field(None, max_length=1000, description="Optional correlation ID echoed by Namsor.")


class PersonalNameGeo(PersonalName):
    countryIso2: Country


class FirstLastName(_Input):
    firstName: Text
    lastName: Text
    id: str | None = Field(None, max_length=1000)


class GetApiKeyInfo(_Input):
    """Read API Key info."""
    operation: Literal["get_api_key_info"] = "get_api_key_info"


class GetApiUsage(_Input):
    """Print current API usage."""
    operation: Literal["get_api_usage"] = "get_api_usage"


class ClassifyNameType(_Input):
    """Infer the likely type of a proper noun (personal name, brand name, place name etc.)"""
    operation: Literal["classify_name_type"] = "classify_name_type"
    properNoun: Text


class ClassifyGender(_Input):
    """Infer the likely gender of a name."""
    operation: Literal["classify_gender"] = "classify_gender"
    firstName: Text
    lastName: Text


class ClassifyGenderGeo(_Input):
    """Infer the likely gender of a name, given a local context (ISO2 country code)."""
    operation: Literal["classify_gender_geo"] = "classify_gender_geo"
    firstName: Text
    lastName: Text
    countryIso2: Country


class ClassifyGenderFull(_Input):
    """Infer the likely gender of a full name, ex. John H. Smith"""
    operation: Literal["classify_gender_full"] = "classify_gender_full"
    fullName: Text


class ClassifyGenderFullGeo(_Input):
    """Infer the likely gender of a full name, given a local context (ISO2 country code)."""
    operation: Literal["classify_gender_full_geo"] = "classify_gender_full_geo"
    fullName: Text
    countryIso2: Country


class ParseName(_Input):
    """Infer the likely first/last name structure of a name, ex. John Smith or SMITH, John or SMITH; John."""
    operation: Literal["parse_name"] = "parse_name"
    nameFull: Text


class ParseNameGeo(_Input):
    """Infer the likely first/last name structure of a name, ex. John Smith or SMITH, John or SMITH; John. For better accuracy, provide a geographic context."""
    operation: Literal["parse_name_geo"] = "parse_name_geo"
    nameFull: Text
    countryIso2: Country


class ParseChineseName(_Input):
    """Infer the likely first/last name structure of a name, ex. 王晓明 -> 王(surname) 晓明(given name)"""
    operation: Literal["parse_chinese_name"] = "parse_chinese_name"
    chineseName: Text


class RomanizeChineseName(_Input):
    """Romanize the Chinese name to Pinyin, ex. 王晓明 -> Wang (surname) Xiaoming (given name)"""
    operation: Literal["romanize_chinese_name"] = "romanize_chinese_name"
    chineseName: Text


class MatchChineseName(_Input):
    """Return a score for matching Chinese name ex. 王晓明 with a romanized name ex. Wang Xiaoming"""
    operation: Literal["match_chinese_name"] = "match_chinese_name"
    chineseSurnameLatin: Text
    chineseGivenNameLatin: Text
    chineseName: Text


class ParseJapaneseName(_Input):
    """Infer the likely first/last name structure of a name, ex. 山本 早苗 or Yamamoto Sanae"""
    operation: Literal["parse_japanese_name"] = "parse_japanese_name"
    japaneseName: Text


class JapaneseKanjiCandidates(_Input):
    """Identify japanese name candidates in KANJI, based on the romanized name ex. Yamamoto Sanae"""
    operation: Literal["japanese_kanji_candidates"] = "japanese_kanji_candidates"
    japaneseSurnameLatin: Text
    japaneseGivenNameLatin: Text


class JapaneseLatinCandidates(_Input):
    """Romanize japanese name, based on the name in Kanji."""
    operation: Literal["japanese_latin_candidates"] = "japanese_latin_candidates"
    japaneseSurnameKanji: Text
    japaneseGivenNameKanji: Text


class MatchJapaneseName(_Input):
    """Return a score for matching Japanese name in KANJI ex. 山本 早苗 with a romanized name ex. Yamamoto Sanae"""
    operation: Literal["match_japanese_name"] = "match_japanese_name"
    japaneseSurnameLatin: Text
    japaneseGivenNameLatin: Text
    japaneseName: Text


class ParseNamesBatch(_Input):
    """Infer the likely first/last name structure of a name, ex. John Smith or SMITH, John or SMITH; John."""
    operation: Literal["parse_names_batch"] = "parse_names_batch"
    personalNames: list[PersonalName] = Field(..., min_length=1, max_length=100)


class ParseNamesGeoBatch(_Input):
    """Infer the likely first/last name structure of a name, ex. John Smith or SMITH, John or SMITH; John. Giving a local context improves precision."""
    operation: Literal["parse_names_geo_batch"] = "parse_names_geo_batch"
    personalNames: list[PersonalNameGeo] = Field(..., min_length=1, max_length=100)


class ParseChineseNamesBatch(_Input):
    """Infer the likely first/last name structure of a name, ex. 王晓明 -> 王(surname) 晓明(given name)."""
    operation: Literal["parse_chinese_names_batch"] = "parse_chinese_names_batch"
    personalNames: list[PersonalName] = Field(..., min_length=1, max_length=100)


class RomanizeChineseNamesBatch(_Input):
    """Romanize a list of Chinese name to Pinyin, ex. 王晓明 -> Wang (surname) Xiaoming (given name)."""
    operation: Literal["romanize_chinese_names_batch"] = "romanize_chinese_names_batch"
    personalNames: list[PersonalName] = Field(..., min_length=1, max_length=100)


class ParseJapaneseNamesBatch(_Input):
    """Infer the likely first/last name structure of a name, ex. 山本 早苗 or Yamamoto Sanae"""
    operation: Literal["parse_japanese_names_batch"] = "parse_japanese_names_batch"
    personalNames: list[PersonalName] = Field(..., min_length=1, max_length=100)


class ClassifyGenderBatch(_Input):
    """Infer the likely gender of up to 100 names, detecting automatically the cultural context."""
    operation: Literal["classify_gender_batch"] = "classify_gender_batch"
    personalNames: list[FirstLastName] = Field(..., min_length=1, max_length=100)


class ClassifyGenderFullBatch(_Input):
    """Infer the likely gender of up to 100 full names, detecting automatically the cultural context."""
    operation: Literal["classify_gender_full_batch"] = "classify_gender_full_batch"
    personalNames: list[PersonalName] = Field(..., min_length=1, max_length=100)


class SetLearning(_Input):
    """Activate/deactivate learning from a source."""
    operation: Literal["set_learning"] = "set_learning"
    learnable: bool


class SetAnonymization(_Input):
    """Activate/deactivate anonymization for a source."""
    operation: Literal["set_anonymization"] = "set_anonymization"
    anonymized: bool


NamsorConfig = Annotated[Union[
    GetApiKeyInfo,
    GetApiUsage,
    ClassifyNameType,
    ClassifyGender,
    ClassifyGenderGeo,
    ClassifyGenderFull,
    ClassifyGenderFullGeo,
    ParseName,
    ParseNameGeo,
    ParseChineseName,
    RomanizeChineseName,
    MatchChineseName,
    ParseJapaneseName,
    JapaneseKanjiCandidates,
    JapaneseLatinCandidates,
    MatchJapaneseName,
    ParseNamesBatch,
    ParseNamesGeoBatch,
    ParseChineseNamesBatch,
    RomanizeChineseNamesBatch,
    ParseJapaneseNamesBatch,
    ClassifyGenderBatch,
    ClassifyGenderFullBatch,
    SetLearning,
    SetAnonymization,
], Field(discriminator="operation")]


class NamsorFullConfig(NodeConfig[NamsorConfig, NamsorAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'get_api_key_info': ('GET', '/api2/json/apiKeyInfo'),
 'get_api_usage': ('GET', '/api2/json/apiUsage'),
 'classify_name_type': ('GET', '/api2/json/nameType/{properNoun}'),
 'classify_gender': ('GET', '/api2/json/gender/{firstName}/{lastName}'),
 'classify_gender_geo': ('GET', '/api2/json/genderGeo/{firstName}/{lastName}/{countryIso2}'),
 'classify_gender_full': ('GET', '/api2/json/genderFull/{fullName}'),
 'classify_gender_full_geo': ('GET', '/api2/json/genderFullGeo/{fullName}/{countryIso2}'),
 'parse_name': ('GET', '/api2/json/parseName/{nameFull}'),
 'parse_name_geo': ('GET', '/api2/json/parseName/{nameFull}/{countryIso2}'),
 'parse_chinese_name': ('GET', '/api2/json/parseChineseName/{chineseName}'),
 'romanize_chinese_name': ('GET', '/api2/json/pinyinChineseName/{chineseName}'),
 'match_chinese_name': ('GET',
                        '/api2/json/chineseNameMatch/{chineseSurnameLatin}/{chineseGivenNameLatin}/{chineseName}'),
 'parse_japanese_name': ('GET', '/api2/json/parseJapaneseName/{japaneseName}'),
 'japanese_kanji_candidates': ('GET',
                               '/api2/json/japaneseNameKanjiCandidates/{japaneseSurnameLatin}/{japaneseGivenNameLatin}'),
 'japanese_latin_candidates': ('GET',
                               '/api2/json/japaneseNameLatinCandidates/{japaneseSurnameKanji}/{japaneseGivenNameKanji}'),
 'match_japanese_name': ('GET',
                         '/api2/json/japaneseNameMatch/{japaneseSurnameLatin}/{japaneseGivenNameLatin}/{japaneseName}'),
 'parse_names_batch': ('POST', '/api2/json/parseNameBatch'),
 'parse_names_geo_batch': ('POST', '/api2/json/parseNameGeoBatch'),
 'parse_chinese_names_batch': ('POST', '/api2/json/parseChineseNameBatch'),
 'romanize_chinese_names_batch': ('POST', '/api2/json/pinyinChineseNameBatch'),
 'parse_japanese_names_batch': ('POST', '/api2/json/parseJapaneseNameBatch'),
 'classify_gender_batch': ('POST', '/api2/json/genderBatch'),
 'classify_gender_full_batch': ('POST', '/api2/json/genderFullBatch'),
 'set_learning': ('GET', '/api2/json/learnable/{source}/{learnable}'),
 'set_anonymization': ('GET', '/api2/json/anonymize/{source}/{anonymized}')}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {str(k).replace(token, "[redacted]"): "[redacted]" if str(k).lower() in {"apikey", "api_key", "token"} else _redact(v, token) for k, v in value.items()}
    return value


class NamsorNode(WorkflowNode):
    integration_type = "automation-namsor"
    connection_evidence = ConnectionEvidence(noun="Namsor account", identity_operation="get_api_key_info", identity_keys=("userId",))

    @classmethod
    def get_config_model(cls):
        return NamsorFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, NamsorFullConfig) or not self.config.credentials:
            raise ValueError("Attach a Namsor API key")
        config = self.config.config
        token = self.config.credentials.api_key
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        # The privacy controls target only the attached key, never another account.
        if config.operation in {"set_learning", "set_anonymization"}:
            values["source"] = token
        def segment(value):
            text = str(value).lower() if isinstance(value, bool) else str(value)
            if text in {".", ".."}:
                raise ValueError("A path value cannot be a dot segment")
            return quote(text, safe="")
        fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{name: segment(values.pop(name)) for name in fields})
        kwargs = {"json": values} if method == "POST" else {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"X-API-KEY": token, "Accept": "application/json"}, **kwargs)
        except (httpx.HTTPError, OSError):
            raise ValueError("Namsor request did not complete; check the provider before retrying") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Namsor response exceeds the size limit")
        if response.status_code != 200:
            try:
                error = response.json()
            except ValueError:
                error = response.text[:2000] or "Namsor rejected the request"
            return _redact({"status": "error", "http_status": response.status_code, "error": error}, token)
        # The contract deliberately declares no response schema for these writes.
        if config.operation in {"set_learning", "set_anonymization"} and not response.content:
            return {"status": "success", "http_status": 200, "data": None, "acknowledged": True}
        try:
            body = response.json()
        except ValueError:
            # Admin endpoints may acknowledge with plain text; this is not readback.
            if config.operation in {"set_learning", "set_anonymization"}:
                return _redact({"status": "success", "http_status": 200, "data": response.text, "acknowledged": True}, token)
            raise ValueError("Namsor returned invalid JSON") from None
        if isinstance(body, dict) and (body.get("error") or body.get("errors") or body.get("success") is False):
            return _redact({"status": "error", "http_status": 200, "error": body}, token)
        if not isinstance(body, dict):
            raise ValueError("Namsor returned an unexpected response shape")
        if config.operation == "get_api_key_info" and not body.get("userId"):
            raise ValueError("Namsor did not return an account identity")
        # Keep the provider's nested arrays, confidence scores and correlation IDs.
        return _redact({"status": "success", "operation": config.operation, "http_status": 200, "data": body}, token)

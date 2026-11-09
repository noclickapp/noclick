"""Jev typed decisions through TypeSafe's published System One API.

Each action performs one contract operation; presets supply editable questions,
not extra provider routes. Model discovery verifies key acceptance only.
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://api.typesafe.ai"
TYPE = "jev_api_key"
Content = Union[str, dict[str, Any], list[Any]]


def _json_bound(value):
    def walk(item, depth=0):
        if depth > 64:
            raise ValueError("JSON content exceeds 64 nesting levels")
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item):
                raise ValueError("JSON object keys must be strings")
            for v in item.values(): walk(v, depth + 1)
        elif isinstance(item, list):
            for v in item: walk(v, depth + 1)
        elif item is not None and type(item) not in {str, int, float, bool}:
            raise ValueError("Use JSON content")
    walk(value)
    try:
        wire = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (ValueError, UnicodeError, OverflowError):
        raise ValueError("Use finite, UTF-8 JSON content") from None
    if len(wire) > 32 * 1024 * 1024:
        raise ValueError("Jev requests must be at most 32 MiB")
    return value


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class JevAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Jev API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://console.typesafe.ai/keys",
            "x-credential-instructions": "Paste your TypeSafe API key. NoClick sends it as a bearer token to api.typesafe.ai. Listing models checks that the key is accepted; it does not identify the account."})
    credential_type: Literal["jev_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class NoulCriteria(_Closed):
    yes: Content | None = Field(None, alias="true")
    no: Content | None = Field(None, alias="false")


class NoulQuestion(_Closed):
    type: Literal["noul"] = "noul"
    instructions: Content | None = None
    criteria: NoulCriteria | None = None


class ChoiceQuestion(_Closed):
    type: Literal["choice"] = "choice"
    instructions: Content | None = None
    criteria: dict[str, Content | None] = Field(..., min_length=1, max_length=255)


class ScoreQuestion(_Closed):
    type: Literal["score"] = "score"
    instructions: Content | None = None
    criteria: list[Content] = Field(..., min_length=1, max_length=10)


class BoxQuestion(_Closed):
    type: Literal["box"] = "box"
    instructions: Content | None = None


Question = Annotated[Union[NoulQuestion, ChoiceQuestion, ScoreQuestion, BoxQuestion], Field(discriminator="type")]


class ImageAsset(_Closed):
    type: Literal["image"] = "image"
    format: Literal["png", "jpg", "jpeg"]
    data_base64: str = Field(..., min_length=1, max_length=44000000, description="Base64 image bytes, without a data URL prefix. This is sent to TypeSafe, not returned in the node output.")

    @field_validator("data_base64")
    @classmethod
    def valid_image_bytes(cls, value):
        try:
            if not base64.b64decode(value, validate=True): raise ValueError()
        except (ValueError, binascii.Error):
            raise ValueError("Supply base64 image bytes") from None
        return value


class ListModelsConfig(_Closed):
    """List the available model names and aliases (one GET /v1/models)."""
    operation: Literal["list_models"] = Field("list_models", json_schema_extra={"ui:hidden": True})


class _Evaluation(_Closed):
    model: str = Field("jev-latest", max_length=256, description="Model name from List Models. Use a vision model for images.")
    state: Content = Field(..., description="Content all questions refer to; text, a JSON object, or an array.")
    assets: dict[str, ImageAsset] | None = Field(None, min_length=1, description="Images keyed by placeholders in state or instructions. Opts into the provider's image danger zone.")
    long_context: bool = Field(False, strict=True, description="Opt into TypeSafe-Danger-Zone-Long-Context: true.")
    _content = field_validator("state", mode="before")(_json_bound)

    @field_validator("model")
    @classmethod
    def nonempty_model(cls, value):
        if not value.strip(): raise ValueError("Choose a model name from List Models")
        return value

    @model_validator(mode="after")
    def bounded_config(self):
        _json_bound(self.model_dump(mode="json", by_alias=True, exclude_none=True))
        return self


class EvaluateQuestionsConfig(_Evaluation):
    """Evaluate multiple named questions of any supported type in one request."""
    operation: Literal["evaluate_questions"] = Field("evaluate_questions", json_schema_extra={"ui:hidden": True})
    questions: dict[str, Question] = Field(..., min_length=1, description="Named noul, choice, score, or box questions; answers retain these names.")


class _Single(_Evaluation):
    question_name: str = Field("result", max_length=256, description="Key of the answer in the returned answers object.")

    @field_validator("question_name")
    @classmethod
    def nonempty_name(cls, value):
        if not value: raise ValueError("Use a question name")
        return value


class AskYesNoConfig(_Single):
    """Return the probability that a statement is true (a Noul question)."""
    operation: Literal["ask_yes_no"] = Field("ask_yes_no", json_schema_extra={"ui:hidden": True})
    instructions: Content = Field(..., description="The statement or yes/no question to evaluate.")
    criteria: NoulCriteria | None = None


class ChooseOptionConfig(_Single):
    """Choose among named options with probabilities and confidence."""
    operation: Literal["choose_option"] = Field("choose_option", json_schema_extra={"ui:hidden": True})
    instructions: Content | None = None
    criteria: dict[str, Content | None] = Field(..., min_length=1, max_length=255)


class RateContentConfig(_Single):
    """Rate content on an ordered zero-based rubric."""
    operation: Literal["rate_content"] = Field("rate_content", json_schema_extra={"ui:hidden": True})
    instructions: Content | None = None
    criteria: list[Content] = Field(..., min_length=1, max_length=10)


class LocateInImageConfig(_Single):
    """Locate an object with normalized box coordinates in a supplied image."""
    model: str = Field("jev-preview", max_length=256, description="Vision-language model name from List Models.")
    operation: Literal["locate_in_image"] = Field("locate_in_image", json_schema_extra={"ui:hidden": True})
    instructions: Content = Field(..., description="What to locate in the image.")
    assets: dict[str, ImageAsset] = Field(..., min_length=1)


class DetectSpamConfig(_Single):
    """Screen a message for unsolicited advertising with a Noul question."""
    operation: Literal["detect_spam"] = Field("detect_spam", json_schema_extra={"ui:hidden": True})
    instructions: Content = "Is this message spam?"
    criteria: NoulCriteria | None = None


class DetectToxicityConfig(_Single):
    """Screen content for toxic language; returns a probability, not a block action."""
    operation: Literal["detect_toxicity"] = Field("detect_toxicity", json_schema_extra={"ui:hidden": True})
    instructions: Content = "Does this content contain toxic or abusive language?"
    criteria: NoulCriteria | None = None


class AnalyzeSentimentConfig(_Single):
    """Classify message tone with editable named choices."""
    operation: Literal["analyze_sentiment"] = Field("analyze_sentiment", json_schema_extra={"ui:hidden": True})
    instructions: Content = "What is the tone of this message?"
    criteria: dict[str, Content | None] = Field(default_factory=lambda: {"angry": "An upset or hostile message", "calm": "A neutral or polite message", "excited": "An enthusiastic or eager message"}, min_length=1, max_length=255)


class ScoreUrgencyConfig(_Single):
    """Score a message's urgency with an editable zero-based rubric."""
    operation: Literal["score_urgency"] = Field("score_urgency", json_schema_extra={"ui:hidden": True})
    instructions: Content = "How urgent is this message?"
    criteria: list[Content] = Field(default_factory=lambda: ["Can wait", "Needs attention this week", "Needs attention today"], min_length=1, max_length=10)


JevConfig = Annotated[Union[ListModelsConfig, EvaluateQuestionsConfig, AskYesNoConfig, ChooseOptionConfig,
    RateContentConfig, LocateInImageConfig, DetectSpamConfig, DetectToxicityConfig,
    AnalyzeSentimentConfig, ScoreUrgencyConfig], Field(discriminator="operation")]


class JevFullConfig(NodeConfig[JevConfig, JevAPIKeyCredential]):
    pass


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class ModelMetadata(_Response):
    name: str
    description: str
    release_date: str


class ModelsResponse(_Response):
    models: list[ModelMetadata]


class NoulAnswer(_Response):
    type: Literal["noul"]
    noul: float


class ChoiceAnswer(_Response):
    type: Literal["choice"]
    choice: str
    confidence: float
    probabilities: dict[str, float]


class ScoreAnswer(_Response):
    type: Literal["score"]
    score: float
    confidence: float
    legend: dict[str, Content]
    probabilities: dict[str, float]


class BoxCoordinates(_Response):
    top: float
    bottom: float
    left: float
    right: float


class BoxAnswer(_Response):
    type: Literal["box"]
    box: BoxCoordinates
    confidence: float | None


Answer = Annotated[Union[NoulAnswer, ChoiceAnswer, ScoreAnswer, BoxAnswer], Field(discriminator="type")]


class Usage(_Response):
    input_tokens: int
    output_tokens: int


class SystemOneResponse(_Response):
    model: str
    answers: dict[str, Answer] = Field(..., min_length=1)
    usage: Usage


def request_body(config):
    if isinstance(config, EvaluateQuestionsConfig):
        questions = config.questions
    else:
        kind = ("box" if isinstance(config, LocateInImageConfig) else
                "choice" if isinstance(config, (ChooseOptionConfig, AnalyzeSentimentConfig)) else
                "score" if isinstance(config, (RateContentConfig, ScoreUrgencyConfig)) else "noul")
        question = {"type": kind, "instructions": config.instructions}
        if getattr(config, "criteria", None) is not None:
            question["criteria"] = config.criteria
        questions = {config.question_name: TypeAdapter(Question).validate_python(question)}
    body = {"model": config.model, "state": config.state,
        "questions": {k: v.model_dump(mode="json", by_alias=True, exclude_none=True) for k, v in questions.items()}}
    if config.assets:
        body["assets"] = {k: v.model_dump() for k, v in config.assets.items()}
    if any(q["type"] == "box" for q in body["questions"].values()) and not config.assets:
        raise ValueError("Box questions need image assets")
    return _json_bound(body)


class JevNode(WorkflowNode):
    integration_type = "automation-jev"
    connection_evidence = ConnectionEvidence(noun="available Jev models", operation="list_models", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return JevFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            return {"status": "error", "error": "Connect a Jev API key"}
        body = None
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        try:
            if isinstance(config, ListModelsConfig):
                method, path = "GET", "/v1/models"
            else:
                method, path = "POST", "/v1/systemone"
                body = request_body(config)
                headers["Content-Type"] = "application/json"
                if config.assets or any(q["type"] == "box" for q in body["questions"].values()):
                    headers["TypeSafe-Danger-Zone-Images"] = "true"
                if config.long_context:
                    headers["TypeSafe-Danger-Zone-Long-Context"] = "true"
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, headers=headers,
                    **({"json": body} if body is not None else {}))
            if response.status_code != 200:
                message = "Jev request failed"
                try:
                    detail = response.json().get("detail")
                    if isinstance(detail, str): message = detail.replace(credential.api_key, "[redacted]")[:2000]
                    elif isinstance(detail, dict) and isinstance(detail.get("message"), str): message = detail["message"].replace(credential.api_key, "[redacted]")[:2000]
                except (ValueError, AttributeError):
                    pass
                return {"status": "error", "http_status": response.status_code,
                    "error": message.replace(credential.api_key, "[redacted]")}
            if len(response.content) > 32 * 1024 * 1024 or response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                raise ValueError("Expected bounded JSON from Jev")
            payload = _json_bound(response.json())
            result = (ModelsResponse if body is None else SystemOneResponse).model_validate(payload).model_dump()
            if body is not None:
                if set(result["answers"]) != set(body["questions"]) or any(result["answers"][k]["type"] != q["type"] for k, q in body["questions"].items()):
                    raise ValueError("Jev answers did not match the requested question names and types")
            return {"status": "success", **result}
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "Jev request could not be completed"}
        except (ValueError, TypeError):
            return {"status": "error", "error": "Jev request or response did not match the supported contract"}

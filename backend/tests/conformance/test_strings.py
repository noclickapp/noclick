"""Generated strings pass the unchanged validators; invalid strings still fail."""
import copy
import json
import re
from typing import Literal

import httpx
import pytest
from pydantic import AnyUrl, BaseModel, EmailStr, Field, Json, field_validator

from tests.conformance import harness
from tests.conformance.strings import PatternError, config_shapes, python_pattern
from tests.conformance.test_inputs import contract_for
from tests.conformance.test_schema_generation import response_contract


@pytest.mark.parametrize(
    "pattern,extra",
    [
        (r"^cus[A-Za-z][A-Za-z0-9_]{0,100}$", {}),
        (r"^lgh_[a-zA-Z0-9]{14}$", {}),
        (r"^lhc_[a-zA-Z0-9]{14}$", {}),
        (r"^noclick-[a-z0-9][a-z0-9-]{1,75}$", {"minLength": 9, "maxLength": 83}),
        (r"^[A-Z]+$", {"minLength": 12, "maxLength": 12}),
        (r"^(cat|longer)[0-9]{2,4}$", {"minLength": 9, "maxLength": 9}),
        (r"^[^/]+/\d{2}$", {}),
        (r"^$", {"maxLength": 0}),
        (r"^(?!a)[ab]{3}$", {}),
        (r"^[abc]{5}(?<=b)$", {}),
    ],
)
def test_patterns_on_generated_inputs_and_responses(pattern, extra):
    schema = {"type": "string", "pattern": pattern, **extra}
    original = copy.deepcopy(schema)
    value = harness.sample({}, schema, examples=False)
    assert re.fullmatch(pattern, value)
    assert extra.get("minLength", 0) <= len(value) <= extra.get("maxLength", 4096)
    assert harness.input_sample({}, schema) == value
    contract_for(schema).validate_request(
        httpx.Request("POST", "https://example.test/items", json=value)
    )
    contract = response_contract(schema)
    request = httpx.Request("POST", "https://example.test/items")
    assert contract.response(request, contract.match(request)[2]).json() == value
    with pytest.raises(ValueError):
        contract_for(schema).validate_request(
            httpx.Request("POST", str(request.url), json="!wrong!")
        )
    with pytest.raises(Exception):
        contract.api.validate_response(
            contract.adapter(request),
            harness.response_adapter(
                httpx.Response(200, json="!wrong!", request=request)
            ),
        )
    assert schema == original


@pytest.mark.parametrize(
    "fmt,bad",
    [
        ("uri", "1"),
        ("email", "1"),
        ("uuid", "1"),
        ("date", "1"),
        ("date-time", "1"),
        ("hostname", "bad host!"),
        ("ipv4", "999.1.1.1"),
        ("byte", "%%%"),
        ("binary", 123),
    ],
)
def test_formats_keep_request_and_response_validation(fmt, bad):
    schema = {"type": "string", "format": fmt}
    value = harness.sample({}, schema)
    contract_for(schema).validate_request(
        httpx.Request("POST", "https://example.test/items", json=value)
    )
    with pytest.raises(ValueError):
        contract_for(schema).validate_request(
            httpx.Request("POST", "https://example.test/items", json=bad)
        )
    contract = response_contract(schema)
    request = httpx.Request("POST", "https://example.test/items")
    assert contract.response(request, contract.match(request)[2]).json() == value
    with pytest.raises(Exception):
        contract.api.validate_response(
            contract.adapter(request),
            harness.response_adapter(httpx.Response(200, json=bad, request=request)),
        )


def test_format_url_alias_and_combined_pattern_length_format():
    assert str(
        AnyUrl(harness.sample({}, {"type": "string", "format": "url"}))
    ).startswith("https://")
    with pytest.raises(ValueError):
        AnyUrl("1")
    schema = {
        "type": "string",
        "format": "uri",
        "pattern": r"^https://example\.test/.*$",
        "minLength": 40,
        "maxLength": 40,
    }
    value = harness.sample({}, schema)
    assert len(value) == 40 and re.fullmatch(schema["pattern"], value)
    contract_for(schema).validate_request(
        httpx.Request("POST", "https://example.test/items", json=value)
    )


EMAIL_PATTERN = r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~\u{0080}-\u{FFFF}-]+@[a-zA-Z0-9\u{0080}-\u{FFFF}]+(?:\.[a-zA-Z0-9\u{0080}-\u{FFFF}]+)*$"


@pytest.mark.parametrize(
    "pattern,good,bad",
    [
        (EMAIL_PATTERN, "élise@exämple.test", "wrong"),
        (r"^(?<word>[a-z]+)-[0-9]+$", "abc-12", "abc-def"),
        (r"^\\u\{0080\}$", r"\u{0080}", "x"),
    ],
)
def test_exact_dialect_translation_validates_and_preserves_source(pattern, good, bad):
    schema = {"type": "string", "pattern": pattern}
    doc = contract_for({}).doc
    doc["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ] = schema
    original = copy.deepcopy(doc)
    contract = harness.Contract(doc)
    contract.validate_request(
        httpx.Request("POST", "https://example.test/items", json=good)
    )
    with pytest.raises(ValueError):
        contract.validate_request(
            httpx.Request("POST", "https://example.test/items", json=bad)
        )
    assert contract.doc == doc == original
    value = harness.input_sample({}, schema)
    assert re.fullmatch(python_pattern(pattern), value)


@pytest.mark.parametrize(
    "pattern",
    [
        r"^\p{L}+$",
        r"^\u{1F600}$",
        r"(?<invalid-name>x)",
        r"[",
        r"(?v:x)",
        r"(?<a>x)?\k<a>",
    ],
)
def test_unsupported_patterns_are_explicit_blockers(pattern):
    with pytest.raises(PatternError, match="Unsupported contract pattern"):
        harness.sample({}, {"type": "string", "pattern": pattern})
    with pytest.raises(harness.FixtureError, match="Unsupported contract pattern"):
        response_contract({"type": "string", "pattern": pattern})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "pattern": "^a$", "minLength": 2},
        {"type": "string", "format": "date", "maxLength": 3},
    ],
)
def test_conflicting_constraints_require_curated_witness(schema):
    with pytest.raises(PatternError, match="curated witness required"):
        harness.sample({}, schema)


async def test_unsupported_pattern_is_reported_without_running_node(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["create"] = "create"

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            pytest.fail("Unsupported contract must not execute")

    monkeypatch.setitem(NODE_REGISTRY, "synthetic", Node)
    monkeypatch.setitem(harness.PROVIDERS, "synthetic", ("synthetic", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(
        harness,
        "load_specs",
        lambda _: [
            response_contract({}).doc
            | {
                "components": {
                    "schemas": {"Unsupported": {"type": "string", "pattern": r"\p{L}"}}
                }
            }
        ],
    )
    report = await harness.run_provider("synthetic")
    assert report["fixture_errors"] == 1 and report["failed"] == 0
    assert (
        "Unsupported contract pattern" in report["operations"][0]["fixture_errors"][0]
    )
    assert not report["operations"][0]["requests"]


def test_node_explicit_metadata_and_pydantic_types():
    class Inputs(BaseModel):
        url: AnyUrl
        email: EmailStr
        payload: Json[dict]
        query: str = Field(
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}
        )
        media: str = Field(json_schema_extra={"ui:widget": "media_upload"})
        day: str = Field(json_schema_extra={"ui:widget": "date"})
        customer_id: str

        @field_validator("query")
        @classmethod
        def object_json(cls, value):
            if not isinstance(json.loads(value), dict):
                raise ValueError("Object required")
            return value

    schema = Inputs.model_json_schema()
    raw = harness.sample(config_shapes(schema), config_shapes(schema), examples=False)
    validated = Inputs.model_validate(raw)
    assert validated.payload == {} and json.loads(validated.query) == {}
    assert raw["media"].startswith("https://") and raw["day"] == "2024-01-01"
    assert raw["customer_id"] == "1"  # IDs have no invented provider semantics.
    for field in ("url", "email", "payload", "query"):
        with pytest.raises(ValueError):
            Inputs.model_validate({**raw, field: "wrong"})


def test_encoded_json_strings_keep_outer_constraints_and_inner_shape():
    schema = {
        "type": "string",
        "contentMediaType": "application/json",
        "contentSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
        "minLength": 20,
        "maxLength": 20,
    }
    value = harness.sample({}, schema)
    assert len(value) == 20 and json.loads(value) == {"name": "1"}
    with pytest.raises(PatternError, match="curated witness required"):
        harness.sample({}, {**schema, "maxLength": 1})


async def test_run_provider_samples_node_metadata_before_validation(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["create"] = "create"
        url: AnyUrl
        payload: str = Field(
            json_schema_extra={"x-code-language": "json", "ui:widget": "code_editor"}
        )

        @field_validator("payload")
        @classmethod
        def object_json(cls, value):
            if not isinstance(json.loads(value), dict):
                raise ValueError("Object required")
            return value

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, config, **kwargs):
            self.config = config

        async def execute(self, _):
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://example.test/items",
                    json=json.loads(self.config.config.payload),
                )
            return {"status": "success"}

    monkeypatch.setitem(NODE_REGISTRY, "synthetic", Node)
    monkeypatch.setitem(harness.PROVIDERS, "synthetic", ("synthetic", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(
        harness, "load_specs", lambda _: [contract_for({"type": "object"}).doc]
    )
    monkeypatch.setattr(harness, "INPUTS", {})
    report = await harness.run_provider("synthetic")
    assert report["passed"] == 1 and report["fixture_errors"] == report["failed"] == 0
    invalid = await harness.run_provider(
        "synthetic", config_overrides={"create": {"payload": "1"}}
    )
    assert invalid["fixture_errors"] == 1 and not invalid["operations"][0]["requests"]


def test_header_patterns_use_shared_generation_and_reject_wrong_wire(monkeypatch):
    schema = {"type": "string", "pattern": "^[A-Z]{3}$"}
    assert re.fullmatch(
        schema["pattern"],
        harness.response_header({}, {"schema": schema, "example": "bad"}),
    )
    contract = response_contract({"type": "string"})
    operation = contract.doc["paths"]["/items"]["post"]
    operation["responses"]["200"]["headers"] = {
        "x-code": {"required": True, "schema": schema}
    }
    contract = harness.Contract(contract.doc)
    monkeypatch.setattr(harness, "FULL", True)
    request = httpx.Request("POST", "https://example.test/items")
    response = contract.response(request, contract.match(request)[2])
    assert re.fullmatch(schema["pattern"], response.headers["x-code"])
    response.headers["x-code"] = "bad"
    with pytest.raises(Exception):
        contract.api.validate_response(
            contract.adapter(request), harness.response_adapter(response)
        )


def test_dialect_translation_respects_schema_and_character_class_boundaries():
    # (?<name>) inside a character class is literal, not a capture declaration.
    pattern = r"^[(?<name>)]$"
    assert python_pattern(pattern) == pattern
    schema = {
        "type": "object",
        "required": ["default"],
        "properties": {"default": {"type": "string", "pattern": r"^\u{0080}$"}},
        "example": {"pattern": r"\p{L}"},
        "x-data": {"pattern": r"\p{L}"},
    }
    original = copy.deepcopy(schema)
    contract = contract_for(schema)
    contract.validate_request(
        httpx.Request("POST", "https://example.test/items", json={"default": "\u0080"})
    )
    with pytest.raises(ValueError):
        contract.validate_request(
            httpx.Request("POST", "https://example.test/items", json={"default": "a"})
        )
    assert schema == original
    shaped = config_shapes(
        {
            "type": "object",
            "properties": {
                "default": {"type": "string", "ui:widget": "email"},
            },
        }
    )
    assert shaped["properties"]["default"]["format"] == "email"

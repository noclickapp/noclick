"""Catalog retries and standards-compliant response handling retain validation."""
import copy
import io
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, Field
from openapi_core.validation.response.exceptions import InvalidData

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for


def response_contract(content, responses=None, version="3.0.3"):
    doc = contract_for({}).doc
    doc["openapi"] = version
    doc["paths"]["/items"]["post"]["responses"] = responses or {
        "200": {"description": "ok", "content": content}
    }
    contract = harness.Contract(doc)
    request = httpx.Request("POST", "https://example.test/items", json={})
    return contract, request, contract.match(request)[2]


async def test_enrichment_keeps_documented_inputs_for_unchanged_operations(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Write(BaseModel):
        operation: Literal["write"]
        id: str
        count: int = 1

    class Read(BaseModel):
        operation: Literal["read"]
        id: str
        count: int = 2

    class Config(BaseModel):
        config: Write | Read = Field(discriminator="operation")
        credentials: dict

    seen = []

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, config, **kwargs):
            self.config = config.config

        async def execute(self, data):
            c = self.config
            seen.append((c.operation, c.id, c.count))
            async with httpx.AsyncClient() as client:
                await client.post("https://example.test/items", json={"count": c.count})
            return {"ok": True}

    doc = contract_for(
        {
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer", "minimum": 2}},
        }
    ).doc
    monkeypatch.setitem(NODE_REGISTRY, "test-retry", Node)
    monkeypatch.setitem(harness.PROVIDERS, "retry", ("test-retry", {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [doc])
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(
        harness,
        "INPUTS",
        {
            "write": {"config": {"id": "documented-write", "count": 1}},
            "read": {"config": {"id": "documented-read", "count": 2}},
        },
    )
    # A documented input is never enriched with synthetic values: the write
    # whose documented count the spec rejects stays a finding, unrerun.
    assert (await harness.run_provider("retry"))["passed"] == 1
    assert seen == [
        ("write", "documented-write", 1),
        ("read", "documented-read", 2),
    ]
    seen.clear()
    assert (
        await harness.run_provider(
            "retry", config_overrides={"write": {"count": 2}}, enrich=False
        )
    )["passed"] == 2
    assert seen == [("write", "documented-write", 2), ("read", "documented-read", 2)]


@pytest.mark.parametrize(
    "scheme,valid,invalid",
    [
        (
            "Bearer",
            ["Bearer token", "bearer token", "BEARER token"],
            ["Basic dTpw", "Bearer ", "Bearer", ""],
        ),
        (
            "BASIC",
            ["Basic dTpw", "basic dTpw"],
            ["Bearer token", "Basic invalid", "Basic dXNlcg==", ""],
        ),
    ],
)
def test_http_auth_case_normalization_preserves_auth_checks(scheme, valid, invalid):
    doc = contract_for({}).doc
    doc["components"] = {
        "securitySchemes": {"Auth": {"type": "http", "scheme": scheme}}
    }
    doc["security"] = [{"Auth": []}]
    original = copy.deepcopy(doc)
    contract = harness.Contract(doc)
    for auth in valid:
        contract.validate_request(
            httpx.Request(
                "POST",
                "https://example.test/items",
                json={},
                headers={"Authorization": auth},
            )
        )
    for auth in invalid:
        with pytest.raises(ValueError):
            contract.validate_request(
                httpx.Request(
                    "POST",
                    "https://example.test/items",
                    json={},
                    headers={"Authorization": auth},
                )
            )
    assert doc == original


@pytest.mark.parametrize("level", ["root", "path", "operation"])
def test_whole_url_variable_uses_catalog_binding_with_strict_origin(level):
    doc = contract_for({}).doc
    owner = {
        "root": doc,
        "path": doc["paths"]["/items"],
        "operation": doc["paths"]["/items"]["post"],
    }[level]
    owner["servers"] = [
        {"url": "{apiBaseUrl}", "variables": {"apiBaseUrl": {"default": ""}}}
    ]
    original = copy.deepcopy(doc)
    contract = harness.Contract(
        doc, server_variables={"api_base_url": "https://provider.test/api/v2"}
    )
    request = httpx.Request("POST", "https://provider.test/api/v2/items", json={})
    contract.validate_request(request)
    contract.response(request, contract.match(request)[2])
    for url in [
        "https://wrong.test/api/v2/items",
        "http://provider.test/api/v2/items",
        "https://provider.test/api/v20/items",
        "https://provider.test:444/api/v2/items",
    ]:
        with pytest.raises(ValueError, match="No spec operation"):
            contract.match(httpx.Request("POST", url, json={}))
    assert doc == original


def test_whole_url_variable_respects_defaults_and_enums():
    doc = contract_for({}).doc
    doc["servers"] = [
        {
            "url": "{base}",
            "variables": {
                "base": {
                    "default": "https://provider.test/api",
                    "enum": ["https://provider.test/api"],
                }
            },
        }
    ]
    harness.Contract(doc).validate_request(
        httpx.Request("POST", "https://provider.test/api/items", json={})
    )
    doc["servers"][0]["variables"]["base"]["default"] = ""
    with pytest.raises(ValueError, match="allowed absolute"):
        harness.Contract(doc, server_url="https://wrong.test/api")
    doc["servers"][0]["variables"]["base"].pop("enum")
    for value in [
        "file:///tmp/api",
        "https://provider.test/api?x=1",
        "https://provider.test/api#fragment",
    ]:
        with pytest.raises(ValueError, match="allowed absolute"):
            harness.Contract(doc, server_variables={"base": value})


@pytest.mark.parametrize(
    "media,body",
    [
        ("text/plain", "1\n00:00:01,000 --> 00:00:02,000\nSubtitles\n"),
        ("text/csv", "name,count\nexample,2\n"),
        ("text/html", "<html><body>Example</body></html>"),
        ("image/png", b"\x89PNG\r\n\x1a\n"),
    ],
)
def test_documented_non_json_response_is_used_verbatim(monkeypatch, media, body):
    monkeypatch.setattr(harness, "FULL", True)
    schema = {
        "type": "string",
        **({"format": "binary"} if isinstance(body, bytes) else {}),
    }
    contract, request, op = response_contract({media: {"schema": schema}})
    monkeypatch.setattr(harness, "WITNESSES", {"POST /items": {"body": body}})
    record = {}
    response = contract.response(request, op, key="POST /items", record=record)
    assert response.content == (body.encode() if isinstance(body, str) else body)
    assert response.headers["content-type"] == media
    assert record["response_source"] == "docs"


@pytest.mark.parametrize("media", ["text/plain", "text/csv", "text/html"])
def test_generated_text_is_not_json_quoted(media, monkeypatch):
    monkeypatch.setattr(harness, "FULL", False)
    contract, request, op = response_contract(
        {media: {"schema": {"type": "string", "enum": ["documented value"]}}}
    )
    assert contract.response(request, op).text == "documented value"


def test_generated_binary_png_is_valid_and_marked_generated(monkeypatch):
    from PIL import Image

    monkeypatch.setattr(harness, "FULL", True)
    monkeypatch.setattr(harness, "WITNESSES", {})
    contract, request, op = response_contract(
        {"image/png": {"schema": {"type": "string", "format": "binary"}}}
    )
    record = {}
    response = contract.response(request, op, record=record)
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG"
    assert image.size == (1, 1)
    image.verify()
    assert record["response_source"] == "generated"


@pytest.mark.parametrize("media", ["*/*", "application/*"])
def test_wildcard_uses_concrete_decoder_and_preserves_schema(media, monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    schema = {
        "type": "object",
        "required": ["count"],
        "properties": {"count": {"type": "integer"}},
    }
    contract, request, op = response_contract({media: {"schema": schema}})
    monkeypatch.setattr(harness, "WITNESSES", {"POST /items": {"body": {"count": 7}}})
    record = {}
    response = contract.response(request, op, key="POST /items", record=record)
    assert response.json() == {"count": 7}
    assert response.headers["content-type"] == "application/json"
    assert record["response_source"] == "docs"
    with pytest.raises(InvalidData, match="not valid"):
        contract.api.validate_response(
            contract.adapter(request),
            harness.response_adapter(
                httpx.Response(200, json={"count": "wrong"}, request=request)
            ),
        )


def test_documented_content_type_selects_declared_media(monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    contract, request, op = response_contract(
        {
            "application/json": {"schema": {"type": "object"}},
            "text/plain": {"schema": {"type": "string", "enum": ["hello"]}},
        }
    )
    monkeypatch.setattr(
        harness,
        "WITNESSES",
        {
            "POST /items": {
                "body": "hello",
                "headers": {"Content-Type": "text/plain; charset=utf-8"},
            }
        },
    )
    response = contract.response(request, op, key="POST /items")
    assert response.text == "hello"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    harness.WITNESSES["POST /items"]["headers"]["Content-Type"] = "image/jpeg"
    with pytest.raises(ValueError, match="Content-Type is not declared"):
        contract.response(request, op, key="POST /items")


def test_csv_object_schema_is_not_silently_reinterpreted(monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    contract, request, op = response_contract(
        {"text/csv": {"schema": {"type": "object"}}}
    )
    monkeypatch.setattr(harness, "WITNESSES", {"POST /items": {"body": "a,b\n1,2\n"}})
    with pytest.raises(ValueError, match="Cannot generate spec-valid response"):
        contract.response(request, op, key="POST /items")


def test_default_only_response_uses_documented_witness_and_validates(monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    definition = {
        "description": "ok",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["count"],
                    "properties": {"count": {"type": "integer"}},
                }
            }
        },
    }
    contract, request, op = response_contract(
        {}, {"default": definition, "400": {"description": "error"}}
    )
    monkeypatch.setattr(
        harness, "WITNESSES", {"POST /items": {"body": {"count": 7}, "status": 201}}
    )
    record = {}
    response = contract.response(request, op, key="POST /items", record=record)
    assert response.status_code == 201
    assert response.json() == {"count": 7}
    assert record["response_source"] == "docs"
    with pytest.raises(InvalidData, match="not valid"):
        contract.api.validate_response(
            contract.adapter(request),
            harness.response_adapter(
                httpx.Response(200, json={"count": "wrong"}, request=request)
            ),
        )
    harness.WITNESSES["POST /items"]["status"] = 400
    with pytest.raises(ValueError, match="requires a 2XX"):
        contract.response(request, op, key="POST /items")


def test_default_generation_and_explicit_success_precedence(monkeypatch):
    monkeypatch.setattr(harness, "WITNESSES", {})
    contract, request, op = response_contract({}, {"default": {"description": "ok"}})
    assert contract.response(request, op).status_code == 200
    assert contract.response(request, op).content == b""
    definition = {
        "description": "ok",
        "content": {"application/json": {"schema": {"type": "integer", "enum": [3]}}},
    }
    contract, request, op = response_contract({}, {"default": definition})
    assert contract.response(request, op).json() == 3
    contract, request, op = response_contract(
        {}, {"201": definition, "default": {"description": "error"}}
    )
    assert contract.response(request, op).status_code == 201


@pytest.mark.parametrize(
    "path,name,value",
    [
        ("/project/{project-slug}/pipeline", "project-slug", "gh/org/repo"),
        ("/insights/{org-slug}/summary", "org-slug", "gh/org"),
    ],
)
def test_circleci_encoded_slugs_under_server_base_path(path, name, value):
    doc = contract_for({}).doc
    doc["servers"] = [{"url": "https://circleci.test/api/v2"}]
    item = doc["paths"].pop("/items")
    item["post"]["parameters"] = [
        {
            "name": name,
            "in": "path",
            "required": True,
            "schema": {"type": "string", "enum": [value]},
        }
    ]
    doc["paths"][path] = item
    contract = harness.Contract(doc)
    actual = path.replace("{" + name + "}", value.replace("/", "%2F"))
    request = httpx.Request(
        "POST", "https://circleci.test/api/v2" + actual + "?page-token=abc", json={}
    )
    assert contract.match(request)[0] == path
    assert contract.adapter(request).parameters.path[name] == value
    contract.validate_request(request)
    contract.response(request, contract.match(request)[2])
    with pytest.raises(ValueError, match="No spec operation"):
        contract.match(
            httpx.Request(
                "POST",
                "https://circleci.test/api/v2" + path.replace("{" + name + "}", value),
                json={},
            )
        )
    with pytest.raises(ValueError):
        contract.validate_request(
            httpx.Request(
                "POST",
                "https://circleci.test/api/v2" + actual.replace("%2F", "%252F"),
                json={},
            )
        )


def test_documented_witness_tries_all_declared_media_before_generation(monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    contract, request, op = response_contract(
        {
            "application/json": {"schema": {"type": "object"}},
            "text/plain": {"schema": {"type": "string", "enum": ["hello"]}},
        }
    )
    monkeypatch.setattr(harness, "WITNESSES", {"POST /items": {"body": "hello"}})
    record = {}
    response = contract.response(request, op, key="POST /items", record=record)
    assert response.text == "hello"
    assert response.headers["content-type"] == "text/plain"
    assert record["response_source"] == "docs"


def test_success_range_precedes_default_in_minimal_mode(monkeypatch):
    monkeypatch.setattr(harness, "FULL", False)
    success = {
        "description": "success",
        "content": {"text/plain": {"schema": {"type": "string", "enum": ["success"]}}},
    }
    error = {
        "description": "error",
        "content": {"text/plain": {"schema": {"type": "string", "enum": ["error"]}}},
    }
    contract, request, op = response_contract({}, {"2XX": success, "default": error})
    assert contract.response(request, op).text == "success"


@pytest.mark.parametrize("media", ["text/plain", "text/csv", "text/html"])
def test_non_json_spec_examples_precede_generated_bodies(monkeypatch, media):
    monkeypatch.setattr(harness, "FULL", True)
    monkeypatch.setattr(harness, "WITNESSES", {})
    contract, request, op = response_contract(
        {media: {"schema": {"type": "string"}, "example": "provider spec example"}}
    )
    record = {}
    response = contract.response(request, op, record=record)
    assert response.text == "provider spec example"
    assert record["response_source"] == "spec_example"


def test_oas31_binary_media_without_schema_generates_valid_png(monkeypatch):
    from PIL import Image

    monkeypatch.setattr(harness, "WITNESSES", {})
    contract, request, op = response_contract({"image/png": {}}, version="3.1.0")
    response = contract.response(request, op)
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG"
    image.verify()


def test_oas31_string_binary_annotation_does_not_bypass_string_constraint(monkeypatch):
    # OAS 3.1 section 4.8.14.3: format no longer specifies content encoding.
    # Customer.io's pin uses the OAS 3.0 binary schema for raw images in 3.1.
    monkeypatch.setattr(harness, "WITNESSES", {})
    contract, request, op = response_contract(
        {"image/png": {"schema": {"type": "string", "format": "binary"}}},
        version="3.1.0",
    )
    with pytest.raises(ValueError, match="not of type 'string'"):
        contract.response(request, op)


def test_error_only_responses_do_not_invent_a_success_shape():
    # Iterable's three embedded-event operations declare just 400 and 401.
    contract, request, op = response_contract(
        {},
        {"400": {"description": "bad request"}, "401": {"description": "unauthorized"}},
    )
    with pytest.raises(ValueError, match="No concrete success response"):
        contract.response(request, op)

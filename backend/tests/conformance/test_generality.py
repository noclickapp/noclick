"""Provider-independent controls for catalog and recursive-schema boundaries."""
import copy
import hashlib
import json
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for


def write_catalog(tmp_path, doc, **entry):
    raw = json.dumps(doc).encode()
    (tmp_path / "spec.json").write_bytes(raw)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "test": {
                    "file": "spec.json",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "version": "1",
                    **entry,
                },
            }
        )
    )


def test_literal_ref_property_loads_and_samples_without_allowing_remote_refs(
    tmp_path, monkeypatch
):
    schema = {
        "type": "object",
        "required": ["$ref"],
        "properties": {
            "$ref": {"type": "string"},
        },
    }
    doc = contract_for(schema).doc
    write_catalog(tmp_path, doc)
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    loaded = harness.load_spec("test")
    assert harness.resolve(loaded, schema["properties"]) == schema["properties"]
    assert harness.sample(loaded, schema) == {"$ref": "1"}
    contract_for(schema).validate_request(
        httpx.Request("POST", "https://example.test/items", json={"$ref": "ok"})
    )
    with pytest.raises(ValueError):
        contract_for(schema).validate_request(
            httpx.Request("POST", "https://example.test/items", json={"$ref": 123})
        )
    # A genuine reference nested under the literally named property is still checked.
    schema["properties"]["$ref"] = {"$ref": "https://example.test/remote.json"}
    write_catalog(tmp_path, contract_for(schema).doc)
    with pytest.raises(ValueError, match="Remote references"):
        harness.load_spec("test")
    with pytest.raises(ValueError, match="External reference"):
        harness.resolve({}, {"$ref": "https://example.test/remote.json"})


def test_allof_annotations_do_not_generate_scalar_placeholders():
    schema = {
        "allOf": [
            {"description": "An object"},
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        ]
    }
    assert harness.sample({}, schema) == {"name": "1"}
    schema["allOf"][0] = {"type": "string"}
    with pytest.raises(ValueError, match="allOf witnesses"):
        harness.sample({}, schema)


def recursive_contract():
    contract = contract_for({"$ref": "#/components/schemas/Parent"})
    contract.doc["components"] = {
        "schemas": {
            "Parent": {
                "type": "object",
                "oneOf": [{"$ref": "#/components/schemas/Child"}],
            },
            "Child": {
                "type": "object",
                "allOf": [
                    {"$ref": "#/components/schemas/Parent"},
                    {"properties": {"name": {"type": "string"}}},
                ],
            },
        }
    }
    return harness.Contract(contract.doc)


@pytest.mark.parametrize(
    "generator", [harness.sample, harness.input_shape, harness.input_sample]
)
def test_recursive_composition_is_bounded(generator):
    contract = recursive_contract()
    schema = {"$ref": "#/components/schemas/Parent"}
    with pytest.raises(ValueError, match="Recursive .*schema"):
        generator(contract.doc, schema)
    # Ordinary nested schemas still produce a useful witness.
    assert generator({}, {"type": "string", "enum": ["ok"]})


def test_reference_cycles_are_bounded():
    with pytest.raises(ValueError, match="Recursive reference"):
        harness.resolve({"a": {"$ref": "#/b"}, "b": {"$ref": "#/a"}}, {"$ref": "#/a"})


def test_recursive_enrichment_is_bounded():
    contract = recursive_contract()
    with pytest.raises(ValueError, match="Recursive input schema"):
        harness.enrich_config(
            contract,
            {"properties": {"extra_params": {}}},
            {},
            [{"spec_operation": "POST /items"}],
        )


async def test_runner_reports_recursive_fixtures_and_catalog_auth(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    contract = recursive_contract()
    with pytest.raises(harness.FixtureError, match="Recursive request schema"):
        contract.validate_request(
            httpx.Request("POST", "https://example.test/items", json={"name": "ok"})
        )

    class Inputs(BaseModel):
        operation: Literal["create"]

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            pass

        async def execute(self, data):
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://example.test/items",
                    json={"name": "ok"},
                    headers={"authorization": "Basic dXNlcjp0b2tlbg=="},
                )
            return {"ok": True}

    monkeypatch.setitem(harness.PROVIDERS, "recursive", ("test-recursive", {}))
    monkeypatch.setitem(NODE_REGISTRY, "test-recursive", Node)
    monkeypatch.setattr(harness, "load_spec", lambda provider: contract.doc)
    monkeypatch.setattr(harness, "spec_entry", lambda provider: (None, {}))
    report = await harness.run_provider("recursive")
    assert report["fixture_errors"] == 1 and report["failed"] == 0
    assert "Recursive request schema" in report["operations"][0]["fixture_errors"][0]

    contract = contract_for({"type": "object"})
    contract.doc.update(
        security=[{"key": []}],
        components={
            "securitySchemes": {
                "key": {"type": "apiKey", "in": "header", "name": "x-key"},
            }
        },
    )
    override = {"scheme": "basic", "source": "https://example.test/docs/auth"}
    monkeypatch.setattr(
        harness, "spec_entry", lambda provider: (None, {"auth_override": override})
    )
    report = await harness.run_provider("recursive")
    assert report["passed"] == 1 and report["auth_checked"] == 1
    assert report["operations"][0]["requests"][0]["auth_override"] == override

    class RecursiveConfig(Config):
        @classmethod
        def model_json_schema(cls):
            return {
                "properties": {
                    "config": {
                        "type": "object",
                        "required": ["operation", "child"],
                        "properties": {
                            "operation": {"const": "create"},
                            "child": {"$ref": "#/properties/config"},
                        },
                    }
                }
            }

    monkeypatch.setattr(Node, "get_config_model", staticmethod(lambda: RecursiveConfig))
    report = await harness.run_provider("recursive")
    assert report["fixture_errors"] == 1 and report["failed"] == 0
    assert (
        "Cannot generate config witness" in report["operations"][0]["fixture_errors"][0]
    )


@pytest.mark.parametrize(
    "style,explode,good,bad",
    [
        ("form", False, "image_ids=1,2", "image_ids=1,0"),
        ("form", True, "image_ids=1&image_ids=2", "image_ids=1,2"),
        (None, None, "image_ids=1&image_ids=2", "image_ids=wrong"),
        ("pipeDelimited", False, "image_ids=1|2", "image_ids=1|0"),
    ],
)
def test_array_parameter_style_and_explode(style, explode, good, bad):
    doc = contract_for({}).doc
    param = {
        "name": "image_ids",
        "in": "query",
        "required": True,
        "schema": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "integer", "minimum": 1},
        },
    }
    if style is not None:
        param.update(style=style, explode=explode)
    doc["paths"]["/items"]["post"]["parameters"] = [param]
    contract = harness.Contract(doc)
    contract.validate_request(
        httpx.Request("POST", "https://example.test/items?" + good, json={})
    )
    for query in [bad, ""]:
        with pytest.raises(ValueError):
            contract.validate_request(
                httpx.Request("POST", "https://example.test/items?" + query, json={})
            )


@pytest.mark.parametrize("location", ["query", "header", "cookie"])
def test_optional_parameters_are_absent_not_null_defaults(location):
    doc = contract_for({}).doc
    param = {
        "name": "limit",
        "in": location,
        "required": False,
        "schema": {"type": "integer", "minimum": 1, "default": None},
    }
    doc["paths"]["/items"]["post"]["parameters"] = [param]
    contract = harness.Contract(doc)
    contract.validate_request(
        httpx.Request("POST", "https://example.test/items", json={})
    )
    for value in ["0", "null", "wrong"]:
        kwargs = (
            {"params": {"limit": value}}
            if location == "query"
            else {
                "headers": {"limit": value}
                if location == "header"
                else {"cookie": f"limit={value}"}
            }
        )
        with pytest.raises(ValueError):
            contract.validate_request(
                httpx.Request("POST", "https://example.test/items", json={}, **kwargs)
            )
    # Required parameters cannot disappear even when a valid default exists.
    param["required"] = True
    param["schema"]["default"] = 1
    with pytest.raises(ValueError):
        harness.Contract(doc).validate_request(
            httpx.Request("POST", "https://example.test/items", json={})
        )


@pytest.mark.parametrize("kind", ["apiKey", "oauth2"])
def test_sourced_auth_override_replaces_spec_placement_only(
    tmp_path, monkeypatch, kind
):
    doc = contract_for({}).doc
    doc.update(
        security=[{"key": []}],
        components={
            "securitySchemes": {
                "key": (
                    {"type": "apiKey", "in": "header", "name": "x-key"}
                    if kind == "apiKey"
                    else {
                        "type": "oauth2",
                        "flows": {
                            "clientCredentials": {
                                "tokenUrl": "https://example.test/token",
                                "scopes": {},
                            }
                        },
                    }
                ),
            }
        },
    )
    override = {"scheme": "basic", "source": "https://example.test/docs/basic-auth"}
    write_catalog(tmp_path, doc, auth_override=override)
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    original = copy.deepcopy(doc)
    req = httpx.Request(
        "POST",
        "https://example.test/items",
        json={},
        headers={"authorization": "Basic dXNlcjp0b2tlbg=="},
    )
    with pytest.raises(ValueError, match="Authentication"):
        harness.Contract(doc).validate_request(req)
    contract = harness.Contract(
        harness.load_spec("test"),
        auth_override=harness.spec_entry("test")[1]["auth_override"],
    )
    contract.validate_request(req)
    assert contract.doc == original
    for auth in [None, "Bearer token", "Basic malformed", "Basic bm9jb2xvbg=="]:
        with pytest.raises(ValueError, match="Authentication"):
            contract.validate_request(
                httpx.Request(
                    "POST",
                    "https://example.test/items",
                    json={},
                    headers={"authorization": auth} if auth else {},
                )
            )
    with pytest.raises(ValueError):
        contract.validate_request(
            httpx.Request(
                "POST",
                "https://example.test/items",
                content="wrong",
                headers={"authorization": "Basic dXNlcjp0b2tlbg=="},
            )
        )


@pytest.mark.parametrize(
    "override",
    [
        {"scheme": "basic"},
        {"scheme": "anything", "source": "https://example.test/docs"},
        {"scheme": "basic", "source": "not-a-url"},
    ],
)
def test_auth_override_requires_supported_scheme_and_source(override):
    with pytest.raises(ValueError, match="Auth override"):
        harness.Contract(contract_for({}).doc, auth_override=override)

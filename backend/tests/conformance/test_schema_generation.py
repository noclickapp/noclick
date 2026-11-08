"""Synthetic schema controls; none of these values are provider examples."""
import copy
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for


def response_contract(schema, version="3.0.3"):
    doc = copy.deepcopy(contract_for({}).doc)
    doc["openapi"] = version
    doc["paths"]["/items"]["post"].pop("requestBody")
    doc["paths"]["/items"]["post"]["responses"]["200"]["content"] = {
        "application/json": {"schema": schema}
    }
    return harness.Contract(doc)


@pytest.mark.parametrize("full", [False, True])
def test_allof_combines_required_and_nested_constraints_before_sampling(full):
    schema = {
        "allOf": [
            {
                "type": "object",
                "required": ["data"],
                "properties": {
                    "data": {
                        "type": "object",
                        "required": ["id", "type"],
                        "properties": {
                            "id": {"type": "string"},
                            "type": {"type": "string"},
                        },
                    }
                },
            },
            {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "object",
                        "properties": {"type": {"enum": ["widgets"]}},
                    }
                },
            },
        ]
    }
    contract = response_contract(schema)
    original = copy.deepcopy(contract.doc)
    assert harness.sample(contract.doc, schema, full=full)["data"] == {
        "id": "1",
        "type": "widgets",
    }
    request = httpx.Request("POST", "https://example.test/items")
    assert (
        contract.response(request, contract.match(request)[2]).json()["data"]["type"]
        == "widgets"
    )
    # Generation never replaces the validating contract with the chosen shape.
    assert contract.doc == original
    with pytest.raises(Exception):
        contract.api.validate_response(
            contract.adapter(request),
            harness.response_adapter(
                httpx.Response(200, json={"data": {}}, request=request)
            ),
        )


@pytest.mark.parametrize("union", ["oneOf", "anyOf"])
def test_union_branch_keeps_parent_properties_and_required(union):
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        union: [{"required": ["name"]}],
    }
    assert harness.sample({}, schema, full=False) == {"name": "1"}
    assert harness.input_sample({}, schema) == {"name": "1"}


def test_composition_does_not_consume_json_depth_budget():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    for _ in range(8):
        schema = {"allOf": [{"description": "annotation"}, schema]}
    assert harness.sample({}, schema, full=True) == {"name": "1"}


def test_required_undeclared_properties_use_additional_properties_schema():
    schema = {"type": "object", "required": ["opaque"]}
    contract = response_contract(schema)
    request = httpx.Request("POST", "https://example.test/items")
    assert contract.response(request, contract.match(request)[2]).json() == {
        "opaque": None
    }
    schema["additionalProperties"] = {"type": "integer", "minimum": 3}
    assert harness.sample({}, schema) == {"opaque": 3}
    schema["additionalProperties"] = False
    with pytest.raises(ValueError, match="undeclared.*additionalProperties is false"):
        harness.sample({}, schema)


def test_oneof_tries_later_branch_but_validates_exclusivity():
    overlapping = {
        "type": "object",
        "required": ["message"],
        "properties": {"message": {"type": "string"}},
    }
    disjoint = {
        "type": "object",
        "required": ["count"],
        "properties": {"count": {"type": "integer"}},
    }
    schema = {"oneOf": [overlapping, overlapping, disjoint]}
    contract = response_contract(schema)
    request = httpx.Request("POST", "https://example.test/items")
    assert contract.response(request, contract.match(request)[2]).json() == {"count": 1}
    impossible = response_contract({"oneOf": [overlapping, overlapping]})
    with pytest.raises(ValueError, match="Cannot generate spec-valid response"):
        impossible.response(request, impossible.match(request)[2])


def test_nested_oneof_with_two_unconstrained_object_branches_is_unsatisfiable():
    # Every object matches both inner alternatives. Non-objects match neither.
    schema = {
        "type": "object",
        "required": ["details"],
        "properties": {
            "details": {
                "oneOf": [
                    {
                        "oneOf": [
                            {"title": "First", "type": "object"},
                            {"title": "Second", "type": "object"},
                        ]
                    }
                ]
            }
        },
    }
    contract = response_contract(schema)
    request = httpx.Request("POST", "https://example.test/items")
    with pytest.raises(ValueError, match="Cannot generate spec-valid response"):
        contract.response(request, contract.match(request)[2])


def test_untyped_union_alternative_can_admit_only_nonobject_witnesses():
    # The first two branches reject every object by overlapping. The third
    # has no type, so required/properties do not constrain scalar instances.
    schema = {
        "oneOf": [
            {"type": "object"},
            {"type": "object"},
            {"required": ["trigger"], "properties": {"trigger": {"type": "string"}}},
        ]
    }
    contract = response_contract(schema)
    request = httpx.Request("POST", "https://example.test/items")
    response = contract.response(request, contract.match(request)[2])
    assert not isinstance(response.json(), dict)
    with pytest.raises(Exception):
        contract.api.validate_response(
            contract.adapter(request),
            harness.response_adapter(
                httpx.Response(200, json={"trigger": "synthetic"}, request=request)
            ),
        )


@pytest.mark.parametrize(
    "typ,extra,good,bad",
    [
        ("string", {"pattern": "^[A-Z]{3}$"}, "ABC", "abc"),
        ("integer", {"minimum": 2}, "3", "1"),
        ("number", {"minimum": 2}, "3.5", "1.5"),
        ("boolean", {}, "true", "invalid"),
        ("array", {"items": {"type": ["integer", "null"], "minimum": 2}}, "2,3", "2,1"),
    ],
)
def test_nullable_31_query_types_keep_all_constraints(typ, extra, good, bad):
    doc = copy.deepcopy(contract_for({}).doc)
    doc["openapi"] = "3.1.0"
    op = doc["paths"]["/items"]["post"]
    op.pop("requestBody")
    op["parameters"] = [
        {
            "name": "value",
            "in": "query",
            "required": True,
            "style": "form",
            "explode": False,
            "schema": {"type": [typ, "null"], **extra},
        }
    ]
    original = copy.deepcopy(doc)
    contract = harness.Contract(doc)
    contract.validate_request(
        httpx.Request("POST", "https://example.test/items", params={"value": good})
    )
    for params in ({"value": bad}, {}):
        with pytest.raises(ValueError):
            contract.validate_request(
                httpx.Request("POST", "https://example.test/items", params=params)
            )
    assert doc == original and contract.doc == original


def test_nullable_string_does_not_decode_literal_null_as_null():
    doc = copy.deepcopy(contract_for({}).doc)
    doc["openapi"] = "3.1.0"
    doc["paths"]["/items"]["post"]["parameters"] = [
        {
            "name": "value",
            "in": "query",
            "required": True,
            "schema": {"type": ["string", "null"], "enum": ["null"]},
        }
    ]
    contract = harness.Contract(doc)
    contract.validate_request(
        httpx.Request("POST", "https://example.test/items?value=null", json={})
    )


def test_nullable_response_sample_uses_non_null_type():
    schema = {
        "type": ["object", "null"],
        "required": ["count"],
        "properties": {"count": {"type": ["integer", "null"], "minimum": 2}},
    }
    contract = response_contract(schema, "3.1.0")
    request = httpx.Request("POST", "https://example.test/items")
    assert contract.response(request, contract.match(request)[2]).json() == {"count": 2}


def test_null_response_witness_is_json_null_instead_of_absent_body():
    contract = response_contract({"type": "null"}, "3.1.0")
    request = httpx.Request("POST", "https://example.test/items")
    response = contract.response(request, contract.match(request)[2])
    assert response.content == b"null" and response.json() is None
    with pytest.raises(Exception):
        contract.api.validate_response(
            contract.adapter(request),
            harness.response_adapter(httpx.Response(200, request=request)),
        )


def test_nullable_parameter_casting_does_not_coerce_json_request_bodies():
    doc = copy.deepcopy(
        contract_for(
            {
                "type": "object",
                "required": ["count"],
                "properties": {"count": {"type": ["integer", "null"], "minimum": 2}},
            }
        ).doc
    )
    doc["openapi"] = "3.1.0"
    contract = harness.Contract(doc)
    for value in (2, None):
        contract.validate_request(
            httpx.Request("POST", "https://example.test/items", json={"count": value})
        )
    for value in ("2", 1, False):
        with pytest.raises(ValueError):
            contract.validate_request(
                httpx.Request(
                    "POST", "https://example.test/items", json={"count": value}
                )
            )


def swagger_with_two_bodies():
    return {
        "swagger": "2.0",
        "info": {"title": "Synthetic", "version": "1"},
        "parameters": {
            "profile": {"in": "body", "name": "profile", "schema": {"type": "object"}}
        },
        "paths": {
            "/items": {
                "parameters": [{"$ref": "#/parameters/profile"}],
                "post": {
                    "operationId": "items.add",
                    "parameters": [
                        {"in": "body", "name": "body", "schema": {"type": "object"}}
                    ],
                    "responses": {"200": {"description": "OK"}},
                },
            }
        },
    }


def test_swagger_multiple_bodies_fail_closed_with_exact_diagnosis():
    doc = swagger_with_two_bodies()
    original = copy.deepcopy(doc)
    with pytest.raises(
        harness.FixtureError, match=r"POST /items .*profile, body.*Lossless conversion"
    ):
        harness.Contract(doc)
    assert doc == original


async def test_swagger_blocker_is_reported_without_executing_node(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["create"] = "create"

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            pytest.fail("An unsupported contract must never execute the node")

    monkeypatch.setitem(NODE_REGISTRY, "synthetic", Node)
    monkeypatch.setitem(harness.PROVIDERS, "synthetic", ("synthetic", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [swagger_with_two_bodies()])
    report = await harness.run_provider("synthetic")
    assert report["checked"] == report["fixture_errors"] == 1
    assert report["failed"] == report["passed"] == report["response_checked"] == 0
    assert not report["operations"][0]["requests"]
    assert "profile, body" in report["operations"][0]["fixture_errors"][0]


@pytest.mark.parametrize("status", ["success", "error"])
async def test_enriched_rerun_preserves_documented_inputs(monkeypatch, status):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["create"] = "create"
        value: str

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
                    json={"value": self.config.config.value},
                )
            return {"status": status}

    doc = contract_for(
        {
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
        }
    ).doc
    monkeypatch.setitem(NODE_REGISTRY, "synthetic", Node)
    monkeypatch.setitem(harness.PROVIDERS, "synthetic", ("synthetic", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [doc])
    monkeypatch.setattr(
        harness, "INPUTS", {"create": {"config": {"value": "documented"}}}
    )

    def must_not_enrich(*args):
        pytest.fail("Documented whole configs must never be synthetically enriched")

    monkeypatch.setattr(harness, "enrich_config", must_not_enrich)
    report = await harness.run_provider(
        "synthetic", config_overrides={"another_operation": {}}
    )
    assert report["passed"] == int(status == "success")
    assert report["failed"] == int(status == "error")
    assert report["operations"][0]["config"]["value"] == "documented"
    assert report["operations"][0]["requests"][0]["body"] == '{"value":"documented"}'

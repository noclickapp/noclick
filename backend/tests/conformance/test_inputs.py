"""Config synthesis repairs fixtures without repairing captured node requests."""
import copy

import httpx
import pytest

from tests.conformance.harness import Contract, enrich_config, input_sample


def contract_for(schema):
    return Contract(
        {
            "openapi": "3.0.3",
            "info": {"title": "Input witnesses", "version": "1"},
            "servers": [{"url": "https://example.test"}],
            "paths": {
                "/items": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {"schema": schema},
                            },
                        },
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )


def test_anyof_required_constraints_retain_parent_properties():
    schema = {
        "type": "object",
        "properties": {"reviewers": {"type": "array", "items": {"type": "string"}}},
        "anyOf": [{"required": ["reviewers"]}],
    }
    value = input_sample({}, schema)
    assert value == {"reviewers": ["1"]}
    contract_for(schema).validate_request(
        httpx.Request("POST", "https://example.test/items", json=value)
    )


def test_input_values_include_writeonly_and_omit_readonly():
    schema = {
        "type": "object",
        "required": ["secret", "id"],
        "properties": {
            "secret": {"type": "string", "writeOnly": True},
            "id": {"type": "string", "readOnly": True},
        },
    }
    assert input_sample({}, schema) == {"secret": "1"}


def test_nonempty_form_objects_and_additional_properties():
    assert input_sample(
        {},
        {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
            },
        },
    ) == {"enabled": False}
    assert input_sample(
        {}, {"type": "object", "additionalProperties": {"type": "integer"}}
    ) == {"conformance": 1}
    assert input_sample(
        {},
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer"},
                },
            },
        },
    ) == [{"amount": 1}]


def test_enrichment_preserves_contract_and_wire():
    schema = {
        "type": "object",
        "required": ["customer", "config"],
        "properties": {
            "customer": {"type": "string"},
            "config": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "format": "uri"},
                },
            },
        },
    }
    contract = contract_for(schema)
    original = copy.deepcopy(contract.doc)
    member = {"properties": {"url": {}, "extra_params": {}}}
    config = {"operation": "create", "url": "1"}
    records = [{"spec_operation": "POST /items", "body": '{"config":{"url":"1"}}'}]
    prior_records = copy.deepcopy(records)
    result = enrich_config(contract, member, config, records)
    assert result["url"] == "https://example.test"
    assert result["extra_params"]["customer"] == "1"
    assert contract.doc == original and records == prior_records
    with pytest.raises(ValueError):
        contract.validate_request(
            httpx.Request(
                "POST", "https://example.test/items", json={"config": {"url": "1"}}
            )
        )


def test_wrong_routes_are_never_rewritten():
    assert enrich_config(
        contract_for({}),
        {"properties": {"id": {}}},
        {"id": "1"},
        [{"url": "https://example.test/wrong"}],
    ) == {"id": "1"}


def test_object_field_is_not_coerced_to_a_broken_list_config():
    contract = contract_for(
        {
            "type": "object",
            "required": ["files"],
            "properties": {
                "files": {"type": "object", "additionalProperties": {"type": "string"}},
            },
        }
    )
    result = enrich_config(
        contract,
        {"properties": {"files": {"type": "array"}}},
        {"files": []},
        [{"spec_operation": "POST /items"}],
    )
    assert isinstance(result["files"], dict)
    # run_provider checks this candidate through the real Pydantic model;
    # incompatible types retain the original failing vector as a node finding.


def test_recursive_inputs_fail_as_fixture_errors():
    doc = {
        "node": {
            "type": "object",
            "required": ["child"],
            "properties": {
                "child": {"$ref": "#/node"},
            },
        }
    }
    with pytest.raises(ValueError, match="Recursive input schema"):
        input_sample(doc, {"$ref": "#/node"})

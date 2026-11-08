"""Mutation controls ensure the harness rejects broken requests, not just snapshots."""
from types import SimpleNamespace

import httpx
import pytest

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from tests.conformance.harness import (
    Contract,
    OperationResult,
    bracket_loads,
    request_adapter,
    response_adapter,
    sample,
)
from werkzeug.datastructures import MultiDict


@pytest.fixture
def spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Mutation control", "version": "1"},
        "servers": [{"url": "https://example.test/v1"}],
        "security": [{"oauth": ["items:write"]}],
        "components": {
            "securitySchemes": {
                "oauth": {
                    "type": "oauth2",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": "https://example.test/auth",
                            "tokenUrl": "https://example.test/token",
                            "scopes": {"items:write": "Write items"},
                        }
                    },
                }
            }
        },
        "paths": {
            "/items/{id}": {
                "post": {
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer", "minimum": 1},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "integer", "maximum": 10},
                        },
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {"name": {"type": "string"}},
                                },
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["id"],
                                        "properties": {"id": {"type": "integer"}},
                                    },
                                }
                            },
                        }
                    },
                }
            }
        },
    }


def request(**kwargs):
    return httpx.Request(
        kwargs.pop("method", "POST"),
        kwargs.pop("url", "https://example.test/v1/items/1?limit=1"),
        headers=kwargs.pop("headers", {"authorization": "Bearer fake"}),
        **({"json": {"name": "example"}} | kwargs),
    )


def test_valid_request_and_generated_response(spec):
    contract = Contract(spec)
    req = request()
    _, _, op = contract.match(req)
    contract.validate_request(req)
    response = contract.response(req, op)
    assert response.json() == {"id": 1}
    contract.api.validate_response(request_adapter(req), response_adapter(response))
    assert contract.response(req, op).content == response.content


@pytest.mark.parametrize(
    "change",
    [
        {"method": "GET"},
        {"url": "http://example.test/v1/items/1?limit=1"},
        {"url": "https://wrong.test/v1/items/1?limit=1"},
        {"url": "https://example.test/v1/items/0?limit=1"},
        {"url": "https://example.test/v1/items/1"},
        {"url": "https://example.test/v1/items/1?limit=11"},
        {"json": {"name": 123}},
        {"json": {}},
        {"headers": {"authorization": "Bearer fake", "content-type": "text/plain"}},
        {"headers": {}},
        {"headers": {"authorization": "Basic fake"}},
        {
            "headers": {},
            "url": "https://example.test/v1/items/1?limit=1&access_token=fake",
        },
    ],
)
def test_request_mutations_are_rejected(spec, change):
    contract = Contract(spec)
    with pytest.raises(Exception):
        contract.validate_request(request(**change))


def test_invalid_generated_witness_is_a_fixture_error(spec):
    spec["paths"]["/items/{id}"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] = {
        "type": "string",
        "pattern": "^[a-z]{5}$",
        "maxLength": 1,
    }
    contract = Contract(spec)
    with pytest.raises(ValueError, match="Cannot generate spec-valid response"):
        contract.response(request(), contract.match(request())[2])


def test_scope_requirements_are_operation_specific_and_respect_alternatives(spec):
    contract = Contract(spec)
    op = {"security": [{"oauth": ["items:write"]}, {"oauth": ["items:admin"]}]}
    node = SimpleNamespace(
        scope_registry=ScopeRegistry(
            "test", {"create": ScopeRequirement(("items:admin",))}
        )
    )
    result = OperationResult("create")
    contract.scopes(node, "create", op, result)
    assert not result.failures
    contract.scopes(node, "other", op, result)
    assert result.scope_checks == 2
    assert "registry []" in result.failures[0]
    # An explicit anonymous alternative means the operation needs no scopes.
    result = OperationResult("create")
    contract.scopes(
        node, "other", {"security": [{}, {"oauth": ["items:write"]}]}, result
    )
    assert not result.failures


def test_bracket_wire_decoding():
    data = MultiDict(
        [
            ("expand[]", "customer"),
            ("expand[]", "invoice"),
            ("items[0][price]", "price_1"),
            ("created[gte]", "123"),
        ]
    )
    assert bracket_loads(True, "expand", "array", data) == ["customer", "invoice"]
    assert bracket_loads(True, "items", "array", data) == [{"price": "price_1"}]
    assert bracket_loads(True, "created", "", data) == {"gte": "123"}
    with pytest.raises(KeyError):
        bracket_loads(True, "missing", "", data)


def test_config_witness_uses_required_fields_and_first_enum():
    schema = {
        "type": "object",
        "required": ["operation", "id", "flag"],
        "properties": {
            "operation": {"enum": ["create", "update"]},
            "id": {"type": "integer", "minimum": 3},
            "flag": {"type": "boolean"},
            "optional": {"type": "string"},
        },
    }
    assert sample(schema, schema, examples=False) == {
        "operation": "create",
        "id": 3,
        "flag": False,
    }


def test_response_schema_rejects_mutation(spec):
    contract = Contract(spec)
    with pytest.raises(Exception):
        contract.api.validate_response(
            request_adapter(request()),
            response_adapter(httpx.Response(200, json={"id": "wrong"})),
        )


@pytest.mark.parametrize("location", ["header", "query", "cookie"])
def test_api_key_must_use_the_named_location(spec, location):
    spec["components"]["securitySchemes"]["key"] = {
        "type": "apiKey",
        "in": location,
        "name": "key",
    }
    spec["security"] = [{"key": []}]
    contract = Contract(spec)
    with pytest.raises(ValueError, match="Authentication"):
        contract.validate_request(request())
    headers = (
        {"key": "fake"}
        if location == "header"
        else {"cookie": "key=fake"}
        if location == "cookie"
        else {}
    )
    url = "https://example.test/v1/items/1?limit=1" + (
        "&key=fake" if location == "query" else ""
    )
    contract.validate_request(request(url=url, headers=headers))


def test_security_schemes_in_one_alternative_are_all_required(spec):
    spec["components"]["securitySchemes"]["key"] = {
        "type": "apiKey",
        "in": "header",
        "name": "x-key",
    }
    spec["security"] = [{"oauth": ["items:write"], "key": []}]
    contract = Contract(spec)
    with pytest.raises(ValueError, match="Authentication"):
        contract.validate_request(request())
    contract.validate_request(
        request(headers={"authorization": "Bearer fake", "x-key": "fake"})
    )


def test_form_brackets_are_validated_against_original_body_schema(spec):
    body = spec["paths"]["/items/{id}"]["post"]["requestBody"]
    body["content"] = {
        "application/x-www-form-urlencoded": {
            "schema": {
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["quantity"],
                            "properties": {
                                "quantity": {"type": "integer", "minimum": 1},
                            },
                        },
                    },
                },
            },
            "encoding": {"items": {"style": "deepObject", "explode": True}},
        }
    }
    contract = Contract(spec)

    def form(value):
        return httpx.Request(
            "POST",
            "https://example.test/v1/items/1?limit=1",
            content=f"items%5B0%5D%5Bquantity%5D={value}",
            headers={
                "authorization": "Bearer fake",
                "content-type": "application/x-www-form-urlencoded",
            },
        )

    contract.validate_request(form(1))
    with pytest.raises(ValueError):
        contract.validate_request(form(0))


def test_literal_path_characters_are_not_regex_wildcards(spec):
    spec["paths"]["/items.json/{id}"] = spec["paths"].pop("/items/{id}")
    contract = Contract(spec)
    contract.validate_request(
        request(url="https://example.test/v1/items.json/1?limit=1")
    )
    with pytest.raises(ValueError, match="No spec operation"):
        contract.validate_request(
            request(url="https://example.test/v1/itemsXjson/1?limit=1")
        )


@pytest.mark.parametrize(
    "fmt,bad,good",
    [
        ("uri", "1", "https://example.test"),
        ("date-time", "yesterday", "2024-01-01T00:00:00Z"),
        ("uri-template", "{unclosed", "https://example.test/{id}"),
    ],
)
def test_format_validation_cannot_silently_skip_optional_dependencies(
    spec, fmt, bad, good
):
    body = spec["paths"]["/items/{id}"]["post"]["requestBody"]
    body["content"]["application/json"]["schema"]["properties"]["name"]["format"] = fmt
    contract = Contract(spec)
    with pytest.raises(ValueError):
        contract.validate_request(request(json={"name": bad}))
    contract.validate_request(request(json={"name": good}))


def test_missing_optional_format_validator_fails_closed(spec, monkeypatch):
    from openapi_schema_validator import oas30_format_checker

    monkeypatch.delitem(oas30_format_checker.checkers, "uri")
    with pytest.raises(ValueError, match="Missing conformance format validators"):
        Contract(spec)


@pytest.mark.parametrize(
    "media", ["application/scim+json", "application/vnd.example.user-invite.v2+json"]
)
def test_json_suffix_media_types_are_validated_as_json(spec, media):
    operation = spec["paths"]["/items/{id}"]["post"]
    operation["requestBody"]["content"] = {media: operation["requestBody"]["content"]["application/json"]}
    operation["responses"]["200"]["content"] = {media: operation["responses"]["200"]["content"]["application/json"]}
    contract = Contract(spec)

    def send(body):
        return request(content=body, headers={"authorization": "Bearer fake", "content-type": media})

    contract.validate_request(send(b'{"name": "example"}'))
    # Decoded as JSON, not passed through as bytes: the schema still rejects a body without `name`.
    with pytest.raises(ValueError):
        contract.validate_request(send(b'{"other": "x"}'))
    with pytest.raises(ValueError):
        contract.validate_request(send(b"not json"))
    req = send(b'{"name": "example"}')
    good = httpx.Response(200, content=b'{"id": 1}', headers={"content-type": media}, request=req)
    contract.api.validate_response(request_adapter(req), response_adapter(good))
    bad = httpx.Response(200, content=b'{"id": "one"}', headers={"content-type": media}, request=req)
    with pytest.raises(Exception):
        contract.api.validate_response(request_adapter(req), response_adapter(bad))

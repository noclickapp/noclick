"""Express-style `/:name` path segments are path templates when the operation declares the parameter."""
import httpx
import pytest

from tests.conformance.harness import Contract


def spec(paths):
    return {
        "openapi": "3.0.3",
        "info": {"title": "Express paths", "version": "1"},
        "servers": [{"url": "https://api.example.test"}],
        "paths": paths,
    }


def operation(*params, method="post"):
    return {
        method: {
            "parameters": [
                {"name": name, "in": "path", "required": True, "schema": {"type": "string", "pattern": "^[a-z0-9]+$"}}
                for name in params
            ],
            "responses": {"204": {"description": "done"}},
        }
    }


def test_declared_colon_segment_is_a_template_and_its_value_is_validated():
    contract = Contract(spec({"/subscription/:id/status": operation("id")}))
    request = httpx.Request("POST", "https://api.example.test/subscription/abc123/status")
    path, method, _ = contract.match(request)
    assert (path, method) == ("/subscription/{id}/status", "post")
    contract.validate_request(request)
    with pytest.raises(ValueError, match="pattern|does not match"):
        contract.validate_request(httpx.Request("POST", "https://api.example.test/subscription/ABC/status"))


def test_two_methods_with_different_parameter_names_keep_their_own_templates():
    contract = Contract(spec({
        "/subscription/:subscriptionId": operation("subscriptionId", method="put"),
        "/subscription/:id": operation("id", method="delete"),
    }))
    assert contract.match(httpx.Request("PUT", "https://api.example.test/subscription/x1"))[0] == (
        "/subscription/{subscriptionId}")
    assert contract.match(httpx.Request("DELETE", "https://api.example.test/subscription/x1"))[0] == (
        "/subscription/{id}")


def test_undeclared_colon_segment_stays_literal_text():
    contract = Contract(spec({"/v1/:batch": {"post": {"responses": {"204": {"description": "done"}}}}}))
    assert contract.match(httpx.Request("POST", "https://api.example.test/v1/:batch"))[0] == "/v1/:batch"
    with pytest.raises(ValueError, match="No spec operation"):
        contract.match(httpx.Request("POST", "https://api.example.test/v1/anything"))


def test_a_template_that_would_collide_with_an_existing_path_is_left_alone():
    contract = Contract(spec({
        "/items/{id}": operation("id", method="get"),
        "/items/:id": operation("id", method="delete"),
    }))
    assert "/items/:id" in contract.doc["paths"] and "/items/{id}" in contract.doc["paths"]


def test_an_unresolvable_reference_elsewhere_in_the_spec_is_left_alone():
    contract = Contract(spec({
        "/subscription/:id": operation("id", method="delete"),
        "/other": {"post": {"parameters": [{"$ref": "#/paths/~1missing/post/parameters/0"}],
                            "responses": {"204": {"description": "done"}}}},
        "/broken/:key": {"get": {"parameters": [{"$ref": "#/components/parameters/Missing"}],
                                 "responses": {"204": {"description": "done"}}}},
    }))
    assert list(contract.doc["paths"]) == ["/subscription/{id}", "/other", "/broken/:key"]

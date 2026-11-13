"""A parameter with no unambiguous serialization blocks only a request that sends it."""
import httpx
import pytest

from tests.conformance.harness import Contract, FixtureError


@pytest.fixture
def contract():
    return Contract({
        "openapi": "3.1.0",
        "info": {"title": "Unsent unions", "version": "1"},
        "servers": [{"url": "https://api.example.test"}],
        "paths": {"/tasks": {"get": {
            "parameters": [
                {"name": "fields", "in": "query", "schema": {"anyOf": [
                    {"type": "string"}, {"type": "array", "items": {"type": "string"}}]}},
                {"name": "scopes", "in": "query", "schema": {"type": ["string", "array"]}},
                {"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 200}},
            ],
            "responses": {"200": {"description": "ok"}},
        }}},
    })


def send(contract, query):
    contract.validate_request(httpx.Request("GET", "https://api.example.test/tasks" + query))


def test_a_request_that_leaves_ambiguous_parameters_out_is_validated_as_usual(contract):
    send(contract, "?limit=200")
    with pytest.raises(ValueError, match="maximum|greater than"):
        send(contract, "?limit=500")


@pytest.mark.parametrize("query", ["?fields=Id", "?scopes=a", "?fields[0]=Id", "?limit=1&fields=Id"])
def test_sending_an_ambiguous_parameter_is_still_a_fixture_error(contract, query):
    with pytest.raises(FixtureError, match="Ambiguous parameter serialization"):
        send(contract, query)

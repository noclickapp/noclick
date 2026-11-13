"""`type: [object, null]` in a YAML spec is the JSON type "null", not YAML's null."""
import httpx
import pytest
import yaml

from tests.conformance.harness import Contract

SPEC = """
openapi: 3.1.0
info: {title: YAML null types, version: "1"}
servers: [{url: "https://api.example.test/v2"}]
paths:
  /cards:
    get:
      parameters:
        - name: filters
          in: query
          style: form
          explode: true
          schema: {type: [object, null], additionalProperties: {type: string}}
        - name: "pagination:page"
          in: query
          schema: {type: [integer, null], minimum: 1}
      responses:
        "200":
          description: Cards
          content:
            application/json:
              schema: {type: array, items: {type: [object, null]}}
"""


@pytest.fixture
def contract():
    doc = yaml.safe_load(SPEC)
    assert doc["paths"]["/cards"]["get"]["parameters"][0]["schema"]["type"] == ["object", None]
    return Contract(doc)


def test_nullable_object_query_parameter_is_serialised_as_an_object(contract):
    contract.validate_request(httpx.Request("GET", "https://api.example.test/v2/cards?pagination%3Apage=2"))
    contract.validate_request(httpx.Request("GET", "https://api.example.test/v2/cards?name=Pikachu"))
    with pytest.raises(ValueError, match="minimum|less than"):
        contract.validate_request(httpx.Request("GET", "https://api.example.test/v2/cards?pagination%3Apage=0"))


def test_every_type_list_reads_yaml_null_as_the_null_type(contract):
    get = contract.doc["paths"]["/cards"]["get"]
    assert [p["schema"]["type"] for p in get["parameters"]] == [["object", "null"], ["integer", "null"]]
    items = get["responses"]["200"]["content"]["application/json"]["schema"]["items"]
    assert items["type"] == ["object", "null"]

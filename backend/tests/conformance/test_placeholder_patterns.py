"""A path parameter pattern that only accepts its own placeholder text is a conversion artefact, not a constraint."""
import httpx
import pytest

from tests.conformance.harness import Contract


def contract(pattern, *, shared=False):
    parameter = {"name": "webhookId", "in": "path", "required": True, "schema": {"type": "string", "pattern": pattern}}
    item = {"delete": {"responses": {"204": {"description": "deleted"}}}}
    if shared:
        item["parameters"] = [{"$ref": "#/components/parameters/WebhookId"}]
    else:
        item["delete"]["parameters"] = [parameter]
    return Contract({
        "openapi": "3.1.0",
        "info": {"title": "Placeholder patterns", "version": "1"},
        "servers": [{"url": "https://api.example.test"}],
        "components": {"parameters": {"WebhookId": parameter}},
        "paths": {"/v1/webhooks/{webhookId}": item},
    })


def delete(contract, value):
    contract.validate_request(httpx.Request("DELETE", f"https://api.example.test/v1/webhooks/{value}"))


@pytest.mark.parametrize("pattern", ["^:webhookId$", ":webhookId", "^\\{webhookId\\}$"])
@pytest.mark.parametrize("shared", [False, True])
def test_a_placeholder_only_pattern_no_longer_rejects_real_ids(pattern, shared):
    delete(contract(pattern, shared=shared), "65f8a2b4c9d7e1234567890b")


@pytest.mark.parametrize("pattern", ["^[a-f0-9]{24}$", "^[0-9]+$"])
def test_a_real_pattern_still_rejects_values_outside_it(pattern):
    c = contract(pattern)
    with pytest.raises(ValueError, match="webhookId"):
        delete(c, "not-a-valid-id!")


def test_a_pattern_ordinary_ids_satisfy_is_kept_even_if_it_also_accepts_the_placeholder():
    c = contract("^[^/]+$")
    assert c.doc["paths"]["/v1/webhooks/{webhookId}"]["delete"]["parameters"][0]["schema"]["pattern"] == "^[^/]+$"


def test_an_unresolvable_parameter_reference_is_left_alone():
    c = Contract({
        "openapi": "3.1.0",
        "info": {"title": "Placeholder patterns", "version": "1"},
        "servers": [{"url": "https://api.example.test"}],
        "paths": {
            "/v1/webhooks/{webhookId}": {"delete": {
                "parameters": [{"name": "webhookId", "in": "path", "required": True,
                                "schema": {"type": "string", "pattern": "^:webhookId$"}}],
                "responses": {"204": {"description": "deleted"}}}},
            "/v1/other": {"get": {"parameters": [{"$ref": "#/paths/~1v1~1missing/get/parameters/0"}],
                                  "responses": {"204": {"description": "ok"}}}},
        },
    })
    delete(c, "65f8a2b4c9d7e1234567890b")

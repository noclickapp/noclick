"""A catalog can document where a provider takes its credential: a header, query parameter or cookie, after a prefix."""
import httpx
import pytest

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for

DOCS = "https://docs.example.test/authentication"


def contract(**placement):
    doc = contract_for({}).doc
    doc["security"] = [{"oauth": []}]
    doc["components"] = {"securitySchemes": {"oauth": {"type": "oauth2", "flows": {"implicit": {
        "authorizationUrl": "https://example.test/auth", "scopes": {}}}}}}
    return harness.Contract(doc, auth_override={**placement, "source": DOCS})


def send(contract, *, headers=None, params=None):
    contract.validate_request(httpx.Request("POST", "https://example.test/items", json={}, headers=headers or {},
                                            params=params))


def test_header_with_a_documented_prefix():
    c = contract(**{"in": "header", "name": "Authorization", "prefix": "Zoho-oauthtoken "})
    send(c, headers={"Authorization": "Zoho-oauthtoken abc"})
    send(c, headers={"authorization": "zoho-oauthtoken abc"})
    for value in ["Bearer abc", "Zoho-oauthtoken ", "abc"]:
        with pytest.raises(ValueError, match="Authentication"):
            send(c, headers={"Authorization": value})
    with pytest.raises(ValueError, match="Authentication"):
        send(c)


def test_bare_key_in_a_header():
    c = contract(**{"in": "header", "name": "Authorization"})
    send(c, headers={"Authorization": "IST.abc123"})
    with pytest.raises(ValueError, match="Authentication"):
        send(c, headers={"X-Other": "IST.abc123"})


def test_query_parameter():
    c = contract(**{"in": "query", "name": "api_key"})
    send(c, params={"api_key": "abc"})
    with pytest.raises(ValueError, match="Authentication"):
        send(c, headers={"X-Api-Key": "abc"})


@pytest.mark.parametrize("override", [
    {"in": "body", "name": "key", "source": DOCS},
    {"in": "header", "name": " ", "source": DOCS},
    {"in": "header", "name": "Authorization", "prefix": 1, "source": DOCS},
    {"in": "header", "name": "Authorization"},
])
def test_a_placement_needs_a_location_a_name_and_a_documentation_url(override):
    with pytest.raises(ValueError, match="Auth override"):
        harness.Contract(contract_for({}).doc, auth_override=override)

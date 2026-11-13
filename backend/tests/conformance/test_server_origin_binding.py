"""A server whose origin the spec leaves unknown takes the catalog's documented server_url, keeping its base path."""
import httpx
import pytest

from tests.conformance.harness import Contract


def contract(server, server_url=None):
    return Contract({
        "openapi": "3.0.3",
        "info": {"title": "Server origins", "version": "1"},
        "servers": [server],
        "paths": {"/certificate/": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }, server_url=server_url)


def match(c, url):
    return c.match(httpx.Request("GET", url))


@pytest.mark.parametrize("server, server_url", [
    ({"url": "{{API_URL}}/v2/public/"}, "https://api.example.test"),
    ({"url": "{base}/v2/public"}, "https://api.example.test"),
    ({"url": "{base}/v2/public", "variables": {"base": {"default": ""}}}, "https://api.example.test"),
    ({"url": "/v2/public"}, "https://api.example.test"),
    ({"url": "/v2/public"}, "https://api.example.test/v2/public"),
])
def test_unknown_origin_binds_to_the_documented_server_url(server, server_url):
    c = contract(server, server_url)
    assert c.doc["servers"][0]["url"] == "https://api.example.test/v2/public"
    match(c, "https://api.example.test/v2/public/certificate/")
    with pytest.raises(ValueError, match="No spec operation"):
        match(c, "https://other.example.test/v2/public/certificate/")
    with pytest.raises(ValueError, match="No spec operation"):
        match(c, "https://api.example.test/certificate/")


def test_a_relative_server_resolves_against_the_documented_origin_only():
    c = contract({"url": "/"}, "https://sandbox.api.example.test/ysl")
    assert c.doc["servers"][0]["url"] == "https://sandbox.api.example.test"
    match(c, "https://sandbox.api.example.test/certificate/")
    with pytest.raises(ValueError, match="No spec operation"):
        match(c, "https://sandbox.api.example.test/ysl/certificate/")


def test_without_a_catalog_server_url_nothing_is_bound():
    assert contract({"url": "{{API_URL}}/v2/public/"}).doc["servers"] == [{"url": "{{API_URL}}/v2/public/"}]
    assert contract({"url": "/v2"}).doc["servers"] == [{"url": "/v2"}]


def test_a_placeholder_with_a_default_keeps_the_specs_own_value():
    server = {"url": "{base}/v2", "variables": {"base": {"default": "https://api.example.test"}}}
    c = contract(server, "https://catalog.example.test")
    assert c.doc["servers"][0]["url"] == "{base}/v2"


def test_absolute_servers_are_never_rebound():
    c = contract({"url": "https://api.example.test/v1"}, "https://catalog.example.test")
    assert c.doc["servers"] == [{"url": "https://api.example.test/v1"}]

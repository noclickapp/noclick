"""A server URL that is a bare host name names that host over HTTPS."""
import httpx
import pytest

from tests.conformance.harness import Contract


def contract(url, *, where="root"):
    operation = {"responses": {"200": {"description": "ok"}}}
    doc = {
        "openapi": "3.0.0",
        "info": {"title": "Bare hosts", "version": "1"},
        "paths": {"/v1/assets": {"get": operation}},
    }
    target = {"root": doc, "path": doc["paths"]["/v1/assets"], "operation": operation}[where]
    target["servers"] = [{"url": url}]
    return Contract(doc)


@pytest.mark.parametrize("where", ["root", "path", "operation"])
def test_bare_host_matches_https_requests_to_that_host(where):
    contract(where=where, url="api.air.inc").match(httpx.Request("GET", "https://api.air.inc/v1/assets"))


def test_bare_host_with_base_path_keeps_the_base_path():
    c = contract("www.zohoapis.com/writer")
    c.match(httpx.Request("GET", "https://www.zohoapis.com/writer/v1/assets"))
    with pytest.raises(ValueError, match="No spec operation"):
        c.match(httpx.Request("GET", "https://www.zohoapis.com/v1/assets"))


def test_bare_host_still_checks_the_host():
    with pytest.raises(ValueError, match="No spec operation"):
        contract("api.air.inc").match(httpx.Request("GET", "https://evil.example.test/v1/assets"))


@pytest.mark.parametrize("url", ["/", "/api", "v1"])
def test_relative_servers_are_unchanged(url):
    assert contract(url).doc["servers"] == [{"url": url}]

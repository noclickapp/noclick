"""Catalog coverage must preserve the provider's request/response constraints."""
import copy
import hashlib
import json
import re
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for


def test_multi_spec_catalog_pins_every_document(tmp_path, monkeypatch):
    specs = []
    for i in range(2):
        doc = contract_for({}).doc
        doc["servers"] = [{"url": f"https://api{i}.example.test"}]
        raw = json.dumps(doc).encode()
        filename = f"{i}.json"
        (tmp_path / filename).write_bytes(raw)
        specs.append(
            dict(
                file=filename,
                sha256=hashlib.sha256(raw).hexdigest(),
                version="1",
                source_url=f"https://example.test/{filename}",
            )
        )
    (tmp_path / "manifest.json").write_text(json.dumps({"test": {"specs": specs}}))
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    docs = harness.load_specs("test")
    assert len(docs) == 2
    (tmp_path / "1.json").write_text("{}")
    with pytest.raises(ValueError, match="hash differs"):
        harness.load_specs("test")
    specs[1]["sha256"] = hashlib.sha256(b"{}").hexdigest()
    specs[1]["version"] = "wrong"
    raw = json.dumps(docs[1]).encode()
    (tmp_path / "1.json").write_bytes(raw)
    specs[1]["sha256"] = hashlib.sha256(raw).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps({"test": {"specs": specs}}))
    with pytest.raises(ValueError, match="version differs"):
        harness.load_specs("test")


async def test_runner_selects_contract_without_merging_components(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["create"]

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            pass

        async def execute(self, data):
            async with httpx.AsyncClient() as client:
                for i in range(2):
                    response = await client.post(
                        f"https://api{i}.example.test/items", json={"value": i}
                    )
                    assert response.json() == {"value": i}
            return {"ok": True}

    docs = []
    for i in range(2):
        doc = copy.deepcopy(contract_for({}).doc)
        doc["servers"] = [{"url": f"https://api{i}.example.test"}]
        doc["components"] = {
            "schemas": {
                "Value": {
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "integer", "enum": [i]}},
                }
            }
        }
        op = doc["paths"]["/items"]["post"]
        op["responses"]["200"]["content"] = {"application/json": {}}
        for content in [
            op["requestBody"]["content"],
            op["responses"]["200"]["content"],
        ]:
            content["application/json"]["schema"] = {
                "$ref": "#/components/schemas/Value"
            }
        docs.append(doc)
    # A catch-all from the first API must not shadow a concrete route in a
    # second API on the same host.
    docs[0]["paths"]["/{path}"] = {
        "post": {
            "servers": [{"url": "https://api1.example.test"}],
            "responses": copy.deepcopy(docs[0]["paths"]["/items"]["post"]["responses"]),
        }
    }
    monkeypatch.setitem(NODE_REGISTRY, "test-multi", Node)
    monkeypatch.setitem(harness.PROVIDERS, "multi", ("test-multi", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: docs)
    report = await harness.run_provider("multi")
    assert report["passed"] == 1
    assert report["coverage"] == {"implemented": 2, "total": 3}
    assert [r["spec_index"] for r in report["operations"][0]["requests"]] == [0, 1]


def test_chargebee_server_variables_and_default_ports():
    server = {
        "url": "{protocol}://{site}.{environment}:{port}/api/v2",
        "variables": {
            "protocol": {"enum": ["https"], "default": "https"},
            "site": {"default": "demo"},
            "environment": {"enum": ["chargebee.com"], "default": "chargebee.com"},
            "port": {"enum": ["443"], "default": "443"},
        },
    }
    for url in [
        "https://test.chargebee.com/api/v2/customers",
        "https://test.chargebee.com:443/api/v2/customers",
    ]:
        assert harness.server_prefix(server, httpx.Request("GET", url)) == "/api/v2"
    doc = contract_for({"type": "object"}).doc
    doc["servers"] = [server]
    contract = harness.Contract(doc)
    request = httpx.Request("POST", "https://test.chargebee.com/api/v2/items", json={})
    contract.validate_request(request)
    contract.response(request, contract.match(request)[2])
    with pytest.raises(ValueError):
        contract.validate_request(
            httpx.Request("POST", "https://test.chargebee.com/api/v2/items", json=[])
        )
    for url in [
        "http://test.chargebee.com/api/v2/customers",
        "https://test.chargebee.com:444/api/v2/customers",
        "https://test.other.com/api/v2/customers",
        "https://test.chargebee.com/api/v20/customers",
    ]:
        assert harness.server_prefix(server, httpx.Request("GET", url)) is None


def test_empty_servers_use_documented_catalog_host():
    doc = contract_for({}).doc
    doc["servers"] = []
    contract = harness.Contract(doc, server_url="https://provider.example.test")
    request = httpx.Request("POST", "https://provider.example.test/items", json={})
    contract.validate_request(request)
    contract.response(request, contract.match(request)[2])
    assert doc["servers"] == []  # pinned source is untouched
    with pytest.raises(ValueError, match="No spec operation"):
        contract.match(
            httpx.Request("POST", "https://wrong.example.test/items", json={})
        )
    harness.Contract(doc).validate_request(
        httpx.Request("POST", "https://example.test/items", json={})
    )


def test_encoded_slashes_match_one_parameter_and_decode_once():
    doc = contract_for({}).doc
    item = doc["paths"].pop("/items")
    item["post"]["parameters"] = [
        {
            "in": "path",
            "name": "slug",
            "required": True,
            "schema": {"type": "string", "enum": ["gh/org/repo", "gh%2Forg%2Frepo"]},
        }
    ]
    doc["paths"]["/items/{slug}"] = item
    contract = harness.Contract(doc)
    for slug in ["gh%2Forg%2Frepo", "gh%252Forg%252Frepo"]:
        request = httpx.Request("POST", "https://example.test/items/" + slug, json={})
        contract.validate_request(request)
        assert contract.adapter(request).parameters.path["slug"] == harness.unquote(
            slug
        )
        contract.response(request, contract.match(request)[2])
    with pytest.raises(ValueError, match="No spec operation"):
        contract.match(
            httpx.Request("POST", "https://example.test/items/gh/org/repo", json={})
        )
    with pytest.raises(ValueError):
        contract.validate_request(
            httpx.Request("POST", "https://example.test/items/wrong", json={})
        )


def test_required_pattern_response_headers_and_documented_witness(monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    doc = contract_for({}).doc
    pattern = r"(<(.*)?>; rel=\"(first|current|last)?\",)*(<(.*)?>; rel=\"(first|current|last)?\")+"
    op = doc["paths"]["/items"]["post"]
    op["responses"]["200"]["headers"] = {
        "Link": {"required": True, "schema": {"type": "string", "pattern": pattern}}
    }
    contract = harness.Contract(doc)
    request = httpx.Request("POST", "https://example.test/items", json={})
    assert re.search(pattern, contract.response(request, op).headers["link"])
    monkeypatch.setattr(
        harness,
        "WITNESSES",
        {
            "POST /items": {
                "body": {},
                "source": "https://example.test/docs",
                "headers": {"link": '<https://example.test/items?page=1>; rel="first"'},
            }
        },
    )
    assert (
        contract.response(request, op, key="POST /items")
        .headers["link"]
        .startswith("<https://")
    )
    assert (
        len(contract.response(request, op, key="POST /items").headers.get_list("link"))
        == 1
    )
    harness.WITNESSES["POST /items"]["headers"]["link"] = "invalid"
    from openapi_core.validation.response.exceptions import InvalidHeader

    with pytest.raises(InvalidHeader):
        contract.response(request, op, key="POST /items")


def test_documented_token_auth_override_checks_prefix_and_value():
    doc = contract_for({}).doc
    doc["security"] = [{"bearer": []}]
    doc["components"] = {
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}
    }
    contract = harness.Contract(
        doc,
        auth_override={
            "scheme": "Token",
            "source": "https://baserow.io/user-docs/database-api",
        },
    )
    for value in ["Token abc", "token abc"]:
        contract.validate_request(
            httpx.Request(
                "POST",
                "https://example.test/items",
                json={},
                headers={"Authorization": value},
            )
        )
    for value in ["Bearer abc", "Token ", "Token"]:
        with pytest.raises(ValueError, match="Authentication"):
            contract.validate_request(
                httpx.Request(
                    "POST",
                    "https://example.test/items",
                    json={},
                    headers={"Authorization": value},
                )
            )
    with pytest.raises(ValueError):
        harness.Contract(
            doc, auth_override={"scheme": "Token", "source": "file:///tmp/docs"}
        )


def test_yaml_catalog_accepts_yml_and_literal_equals(tmp_path, monkeypatch):
    raw = b"openapi: 3.0.3\ninfo: {title: Analytics, version: '1'}\npaths: {}\nexample: =\n"
    (tmp_path / "spec.yml").write_bytes(raw)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "test": {
                    "file": "spec.yml",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "version": "1",
                }
            }
        )
    )
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    assert harness.load_specs("test")[0]["example"] == "="


def test_yaml_catalog_keeps_unquoted_dates_as_written(tmp_path, monkeypatch):
    raw = (
        b"openapi: 3.0.3\ninfo: {title: Events, version: '1'}\npaths: {}\n"
        b"example: {start_at: 2024-05-01T10:00:00Z, day: 2024-05-01}\n"
    )
    (tmp_path / "spec.yaml").write_bytes(raw)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "test": {
                    "file": "spec.yaml",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "version": "1",
                }
            }
        )
    )
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    assert harness.load_specs("test")[0]["example"] == {
        "start_at": "2024-05-01T10:00:00Z",
        "day": "2024-05-01",
    }


@pytest.mark.parametrize(
    "specs",
    [
        [],
        [{}],
        [{"file": "a", "sha256": "x", "version": "1", "source_url": "file:///tmp/a"}],
    ],
)
def test_multi_spec_requires_pins_and_public_source(tmp_path, monkeypatch, specs):
    (tmp_path / "manifest.json").write_text(json.dumps({"test": {"specs": specs}}))
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    with pytest.raises(ValueError):
        harness.load_specs("test")


@pytest.mark.parametrize(
    "url",
    ["https://example.test/api", "//example.test/api", "https://[2001:db8::1]:443/api"],
)
def test_literal_and_protocol_relative_servers_keep_host_and_port_checks(url):
    actual = "https:" + url if url.startswith("//") else url
    assert (
        harness.server_prefix({"url": url}, httpx.Request("GET", actual + "/items"))
        == "/api"
    )
    assert (
        harness.server_prefix(
            {"url": url}, httpx.Request("GET", "https://wrong.test/api/items")
        )
        is None
    )

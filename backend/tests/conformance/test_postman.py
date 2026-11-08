"""Postman collection evidence is request-checked and example-only."""
import copy
import hashlib
import json
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from tests.conformance import harness
from tests.conformance.postman import PostmanContract


@pytest.fixture
def collection():
    # Artificial contract for harness mutation controls, never provider evidence.
    return {
        "info": {
            "name": "Control",
            "version": "1",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [{"key": "base", "value": "https://example.test/v1"}],
        "auth": {"type": "bearer"},
        "item": [
            {
                "name": "create",
                "request": {
                    "method": "POST",
                    "url": {
                        "host": ["{{base}}"],
                        "path": ["items", ":id"],
                        "query": [{"key": "limit", "value": "1"}],
                    },
                    "header": [
                        {"key": "X-Required", "value": "yes"},
                        {"key": "Content-Type", "value": "application/json"},
                        {"key": "X-Disabled", "value": "no", "disabled": True},
                    ],
                    "body": {
                        "mode": "raw",
                        "raw": '{"data":{"name":"value"},"rows":[{"id":1}]}',
                    },
                },
                "response": [
                    {
                        "code": 200,
                        "header": [{"key": "X-Published", "value": "yes"}],
                        "body": '{ "ok": true }',
                    },
                    {
                        "code": 201,
                        "header": [],
                        "body": '{"other":true}',
                        "originalRequest": {
                            "body": {"mode": "raw", "raw": '{"data":{"extra":1}}'}
                        },
                    },
                ],
            }
        ],
    }


def request(**kwargs):
    return httpx.Request(
        kwargs.pop("method", "POST"),
        kwargs.pop("url", "https://example.test/v1/items/1?limit=1"),
        headers=kwargs.pop(
            "headers",
            {
                "Authorization": "Bearer fake",
                "X-Required": "yes",
                "Content-Type": "application/json",
            },
        ),
        **({"json": {"data": {"name": "x", "extra": 1}, "rows": [{"id": 2}]}} | kwargs),
    )


def test_request_and_verbatim_response(collection):
    original = copy.deepcopy(collection)
    c = PostmanContract(collection)
    req = request()
    c.validate_request(req)
    op = c.match(req)[2]
    r = c.response(req, op)
    assert r.content == b'{ "ok": true }'
    assert r.headers["x-published"] == "yes" and "content-type" not in r.headers
    assert c.response(req, op, example_index=1).status_code == 201
    assert collection == original


@pytest.mark.parametrize(
    "mutation",
    [
        {"url": "https://wrong.test/v1/items/1?limit=1"},
        {"url": "https://example.test/v1/unknown/1?limit=1"},
        {"url": "https://example.test/v1/items/1/extra?limit=1"},
        {"method": "GET"},
        {"url": "https://example.test/v1/items/1?surprise=1"},
        {
            "headers": {
                "Authorization": "Bearer fake",
                "Content-Type": "application/json",
            }
        },
        {
            "headers": {
                "Authorization": "Basic fake",
                "Content-Type": "application/json",
                "X-Required": "yes",
            }
        },
        {
            "headers": {
                "Authorization": "Bearer fake",
                "Content-Type": "text/plain",
                "X-Required": "yes",
            }
        },
        {"json": {"data": {"missing": 1}}},
        {"json": {"rows": [{"missing": 1}]}},
        {"json": {"name": "wrong nesting"}},
    ],
)
def test_request_mutations(collection, mutation):
    with pytest.raises(ValueError):
        PostmanContract(collection).validate_request(request(**mutation))


@pytest.mark.parametrize("path", [":id", "{{id}}"])
def test_variable_segments_and_literal_punctuation(collection, path):
    req = collection["item"][0]["request"]
    req["url"]["path"] = ["items.json", path]
    c = PostmanContract(collection)
    c.validate_request(
        request(url="https://example.test/v1/items.json/abc%2Fdef?limit=1")
    )
    with pytest.raises(ValueError):
        c.match(request(url="https://example.test/v1/itemsXjson/abc?limit=1"))


def test_missing_examples_never_generate(collection):
    collection["item"][0]["response"] = []
    c = PostmanContract(collection)
    with pytest.raises(harness.FixtureError, match="no published example response"):
        c.response(
            request(), c.match(request())[2], witnesses={"anything": {"body": {}}}
        )


def pin(tmp_path, monkeypatch, collection):
    raw = json.dumps(collection).encode()
    (tmp_path / "collection.json").write_bytes(raw)
    entry = {
        "file": "collection.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "version": collection.get("info", {}).get("version"),
        "source_url": "https://example.test/collection.json",
        "format": "postman",
    }
    (tmp_path / "manifest.json").write_text(json.dumps({"test": entry}))
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    return entry


@pytest.mark.parametrize("version", ["2.0.0", "2.1.0"])
def test_pins(collection, tmp_path, monkeypatch, version):
    collection["info"][
        "schema"
    ] = f"https://schema.getpostman.com/json/collection/v{version}/collection.json"
    pin(tmp_path, monkeypatch, collection)
    assert harness.load_specs("test") == [collection]


@pytest.mark.parametrize(
    "change,match",
    [
        ({"sha256": "wrong"}, "hash differs"),
        ({"version": "wrong"}, "version differs"),
        ({"source_url": "file:///tmp/local"}, "source_url"),
        ({"format": "openapi"}, "require format"),
    ],
)
def test_bad_pins(collection, tmp_path, monkeypatch, change, match):
    entry = pin(tmp_path, monkeypatch, collection)
    entry.update(change)
    (tmp_path / "manifest.json").write_text(json.dumps({"test": entry}))
    with pytest.raises(ValueError, match=match):
        harness.load_spec("test")


def test_non_postman_file_refused(tmp_path, monkeypatch):
    pin(
        tmp_path,
        monkeypatch,
        {"openapi": "3.0.3", "info": {"version": "1"}, "paths": {}},
    )
    with pytest.raises(ValueError, match="Expected a Postman"):
        harness.load_spec("test")


def test_no_undocumented_host_binding(collection):
    collection["variable"] = []
    c = PostmanContract(
        collection,
        server_url="https://example.test/v1",
        server_variables={"base": "https://example.test/v1"},
    )
    with pytest.raises(ValueError, match="No spec operation"):
        c.match(request())


@pytest.mark.parametrize(
    "mode,content_type,body",
    [
        ("urlencoded", "application/x-www-form-urlencoded", "name=value"),
        (
            "formdata",
            "multipart/form-data; boundary=example",
            '--example\r\nContent-Disposition: form-data; name="name"\r\n\r\nvalue\r\n--example--\r\n',
        ),
    ],
)
def test_form_fields(collection, mode, content_type, body):
    req = collection["item"][0]["request"]
    req["body"] = {"mode": mode, mode: [{"key": "name", "value": "value"}]}
    req["header"] = [{"key": "X-Required", "value": "yes"}]
    c = PostmanContract(collection)

    def send(value):
        return request(
            content=value,
            headers={
                "Authorization": "Bearer fake",
                "X-Required": "yes",
                "Content-Type": content_type,
            },
        )

    c.validate_request(send(body))
    with pytest.raises(ValueError, match="Undocumented Postman body"):
        c.validate_request(
            send(
                body.replace("name=value", "unknown=value").replace(
                    'name="name"', 'name="unknown"'
                )
            )
        )


@pytest.mark.parametrize("encoded", [False, True])
async def test_runner_replays_all_responses_and_preserves_node_guards(
    collection, monkeypatch, encoded
):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["create"]

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    seen = []

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            pass

        async def execute(self, data):
            async with httpx.AsyncClient() as client:
                response = await client.send(request())
                seen.append(response.content)
                assert response.json().get("ok"), "existing node guard"
            return {"ok": True}

    monkeypatch.setitem(NODE_REGISTRY, "test-postman", Node)
    if encoded:
        for example in collection["item"][0]["response"]:
            example["header"] += [
                {"key": "Content-Encoding", "value": "gzip"},
                {"key": "Content-Length", "value": "9999"},
            ]
    monkeypatch.setitem(harness.PROVIDERS, "postman", ("test-postman", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [collection])
    report = await harness.run_provider("postman")
    assert set(seen) == {b'{ "ok": true }', b'{"other":true}'}
    assert report["failed"] >= 1
    assert report["fixture_errors"] == 0
    assert any(
        "existing node guard" in f
        for op in report["operations"]
        for f in op["failures"]
    )
    assert all(
        req["contract_format"] == "postman"
        for op in report["operations"]
        for req in op["requests"]
    )


@pytest.mark.parametrize("client_kind", ["httpx", "aiohttp"])
async def test_encoded_invalid_json_is_a_node_parser_failure(
    collection, monkeypatch, client_kind
):
    import aiohttp
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
            req = request(json={"data": {"name": "x"}})
            if client_kind == "aiohttp":
                async with aiohttp.ClientSession() as client:
                    async with client.request(
                        req.method, str(req.url), headers=req.headers, data=req.content
                    ) as response:
                        return await response.json()
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.send(req)
                    return response.json()

    collection["item"][0]["response"] = [
        {
            "code": 200,
            "header": [
                {"key": "Content-Encoding", "value": "gzip"},
                {"key": "Content-Length", "value": "9999"},
                {"key": "Content-Type", "value": "application/json"},
            ],
            "body": '{"invalid":',
        }
    ]
    monkeypatch.setitem(NODE_REGISTRY, "test-postman-invalid", Node)
    monkeypatch.setitem(
        harness.PROVIDERS, "postman-invalid", ("test-postman-invalid", {})
    )
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [collection])
    report = await harness.run_provider("postman-invalid")
    assert report["failed"] == 1
    assert report["passed"] == report["fixture_errors"] == 0
    result = report["operations"][0]
    assert (
        result["requests"][0]["response_sha256"]
        == hashlib.sha256(b'{"invalid":').hexdigest()
    )
    assert any("JSONDecodeError" in failure for failure in result["failures"])


async def test_openapi_match_cannot_be_downgraded_by_postman(collection, monkeypatch):
    from nodes.core.registry import NODE_REGISTRY
    from tests.conformance.test_inputs import contract_for

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
                await client.post("https://example.test/items", json={"surprise": 1})
            return {"ok": True}

    collection["item"][0]["request"] = {
        "method": "POST",
        "url": "https://example.test/items",
        "body": {"mode": "raw", "raw": '{"surprise":1}'},
    }
    collection.pop("auth")
    openapi = contract_for({"type": "object", "additionalProperties": False}).doc
    monkeypatch.setitem(NODE_REGISTRY, "test-mixed-postman", Node)
    monkeypatch.setitem(harness.PROVIDERS, "mixed-postman", ("test-mixed-postman", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [collection, openapi])
    report = await harness.run_provider("mixed-postman")
    assert report["failed"] == 1
    assert report["operations"][0]["requests"][0]["spec_index"] == 1
    assert any(f.startswith("request:") for f in report["operations"][0]["failures"])


@pytest.mark.parametrize("kind", ["basic", "apikey-header", "apikey-query"])
def test_auth_placement_is_checked(collection, kind):
    import base64

    if kind == "basic":
        collection["auth"] = {"type": "basic"}
        value = "Basic " + base64.b64encode(b"name:secret").decode()
        good = request(
            headers={
                "Authorization": value,
                "X-Required": "yes",
                "Content-Type": "application/json",
            }
        )
    else:
        location = kind.split("-")[1]
        collection["auth"] = {
            "type": "apikey",
            "apikey": [
                {"key": "key", "value": "api-key"},
                {"key": "in", "value": location},
            ],
        }
        good = (
            request(
                headers={
                    "api-key": "fake",
                    "X-Required": "yes",
                    "Content-Type": "application/json",
                }
            )
            if location == "header"
            else request(url="https://example.test/v1/items/1?limit=1&api-key=fake")
        )
    c = PostmanContract(collection)
    c.validate_request(good)
    with pytest.raises(ValueError, match="Authentication"):
        c.validate_request(request())


async def test_anyof_operations_are_each_executed(collection, monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class First(BaseModel):
        operation: Literal["first"]

    class Second(BaseModel):
        operation: Literal["second"]

    class Config(BaseModel):
        config: First | Second
        credentials: dict

    seen = []

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            self.operation = kwargs["config"].config.operation

        async def execute(self, data):
            seen.append(self.operation)
            async with httpx.AsyncClient() as client:
                await client.send(request())
            return {"ok": True}

    assert "anyOf" in Config.model_json_schema()["properties"]["config"]
    monkeypatch.setitem(NODE_REGISTRY, "test-postman-anyof", Node)
    monkeypatch.setitem(harness.PROVIDERS, "postman-anyof", ("test-postman-anyof", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [collection])
    report = await harness.run_provider("postman-anyof")
    assert report["passed"] == 4
    assert sorted(seen) == ["first", "first", "second", "second"]


def test_template_values_do_not_hide_request_keys(collection):
    collection["item"][0]["request"]["body"][
        "raw"
    ] = '{"data":{"count":{{count}},"name":"{{name}}"}}'
    collection["item"][0]["response"] = []
    c = PostmanContract(collection)
    c.validate_request(request(json={"data": {"count": 1, "name": "x"}}))
    with pytest.raises(ValueError, match="Undocumented Postman body"):
        c.validate_request(request(json={"data": {"absent": 1}}))


def test_no_version_is_an_explicit_pin(collection, tmp_path, monkeypatch):
    collection["info"].pop("version")
    pin(tmp_path, monkeypatch, collection)
    assert harness.load_spec("test") == collection


async def test_all_examples_of_every_call_are_replayed(collection, monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["create"]

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    second = copy.deepcopy(collection["item"][0])
    second["request"]["url"]["path"] = ["lookup", ":id"]
    collection["item"].insert(0, second)
    seen = {"lookup": set(), "items": set()}

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            pass

        async def execute(self, data):
            async with httpx.AsyncClient() as client:
                for path in ("lookup", "items"):
                    response = await client.send(
                        request(url=f"https://example.test/v1/{path}/1?limit=1")
                    )
                    seen[path].add(response.content)
            return {"ok": True}

    monkeypatch.setitem(NODE_REGISTRY, "test-postman-multi-call", Node)
    monkeypatch.setitem(
        harness.PROVIDERS, "postman-multi-call", ("test-postman-multi-call", {})
    )
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [collection])
    report = await harness.run_provider("postman-multi-call")
    assert all(
        values == {b'{ "ok": true }', b'{"other":true}'} for values in seen.values()
    )
    assert report["failed"] == report["fixture_errors"] == 0
    assert all(len(op["requests"]) == 2 for op in report["operations"])


def test_error_status_and_duplicate_response_headers_are_verbatim(collection):
    example = collection["item"][0]["response"][0]
    example["code"] = 429
    example["header"] = [
        {"key": "Set-Cookie", "value": "a=1"},
        {"key": "Set-Cookie", "value": "b=2"},
    ]
    c = PostmanContract(collection)
    response = c.response(request(), c.match(request())[2])
    assert response.status_code == 429
    assert response.headers.get_list("set-cookie") == ["a=1", "b=2"]
    assert response.content == example["body"].encode()


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br"])
def test_decoded_example_drops_only_obsolete_wire_headers(collection, encoding):
    example = collection["item"][0]["response"][0]
    example["body"] = '{ "message": "café", "template": "{{literal}}" }\n'
    example["code"] = 422
    example["header"] = [
        {"key": "cOnTeNt-EnCoDiNg", "value": encoding},
        {"key": "Content-Length", "value": "9999"},
        {"key": "Content-Type", "value": "application/problem+json"},
        {"key": "Set-Cookie", "value": "a=1"},
        {"key": "Set-Cookie", "value": "b=2"},
        {"key": "X-Published", "value": "unchanged"},
    ]
    original = copy.deepcopy(collection)
    c = PostmanContract(collection)
    response = c.response(request(), c.match(request())[2])
    assert response.content == example["body"].encode("utf-8")
    assert response.json() == {"message": "café", "template": "{{literal}}"}
    assert response.status_code == 422
    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == str(len(response.content))
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers.get_list("set-cookie") == ["a=1", "b=2"]
    assert response.headers["x-published"] == "unchanged"
    assert collection == original


@pytest.mark.parametrize("length", ["9999", "14"])
def test_saved_body_length_matches_replayed_bytes(collection, length):
    example = collection["item"][0]["response"][0]
    example["header"] = [{"key": "Content-Length", "value": length}]
    c = PostmanContract(collection)
    response = c.response(request(), c.match(request())[2])
    assert response.headers["content-length"] == str(len(response.content))


def test_single_brace_path_is_encoded_literal_not_a_variable(collection):
    collection["item"][0]["request"]["url"]["path"] = ["items", "{id}"]
    c = PostmanContract(collection)
    c.validate_request(request(url="https://example.test/v1/items/%7Bid%7D?limit=1"))
    for path in ("123", "other", "%7Bother%7D", "%7Bid%7D/extra"):
        with pytest.raises(ValueError, match="No spec operation"):
            c.match(request(url=f"https://example.test/v1/items/{path}?limit=1"))


def test_single_brace_host_cannot_be_bound_by_catalog_or_request(collection):
    collection["item"][0]["request"]["url"] = "https://{dc_id}.example.test/items/:id"
    c = PostmanContract(
        collection,
        server_url="https://us1.example.test",
        server_variables={"dc_id": "us1"},
    )
    for host in ("us1.example.test", "evil.example.test", "example.test"):
        with pytest.raises(ValueError, match="single-brace hosts are literal"):
            c.match(request(url=f"https://{host}/items/123"))


async def test_runner_retains_postman_host_rejection_reason(collection, monkeypatch):
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
                await client.send(request(url="https://us1.example.test/items/123"))
            return {"ok": True}

    collection["item"][0]["request"]["url"] = "https://{dc_id}.example.test/items/:id"
    monkeypatch.setitem(NODE_REGISTRY, "test-postman-host", Node)
    monkeypatch.setitem(harness.PROVIDERS, "postman-host", ("test-postman-host", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [collection])
    report = await harness.run_provider("postman-host")
    assert report["failed"] == 1
    assert (
        report["passed"] == report["fixture_errors"] == report["response_checked"] == 0
    )
    assert any(
        "single-brace hosts are literal" in failure
        for failure in report["operations"][0]["failures"]
    )


def test_catalog_auth_cannot_override_collection_auth(collection):
    c = PostmanContract(
        collection,
        auth_override={"scheme": "Token", "source": "https://example.test/docs"},
    )
    c.validate_request(request())
    with pytest.raises(ValueError, match="Authentication"):
        c.validate_request(
            request(
                headers={
                    "Authorization": "Token fake",
                    "X-Required": "yes",
                    "Content-Type": "application/json",
                }
            )
        )
    with pytest.raises(ValueError, match="Authentication"):
        c.validate_request(
            request(
                headers={
                    "Authorization": "Bearer  ",
                    "X-Required": "yes",
                    "Content-Type": "application/json",
                }
            )
        )


def test_json_fields_cannot_hide_behind_another_media_type(collection):
    req = collection["item"][0]["request"]
    req["header"] = [{"key": "X-Required", "value": "yes"}]
    c = PostmanContract(collection)
    headers = {
        "Authorization": "Bearer fake",
        "X-Required": "yes",
        "Content-Type": "text/example",
    }
    c.validate_request(request(json={"data": {"name": "x"}}, headers=headers))
    with pytest.raises(ValueError, match="Undocumented Postman body"):
        c.validate_request(
            request(json={"data": {"name": "x", "unknown": 1}}, headers=headers)
        )


@pytest.mark.parametrize(
    "status,behavior,passes",
    [
        (400, "raise", True),
        (404, "raise", True),
        (409, "raise", True),
        (400, "http-status", True),
        (400, "envelope", True),
        (400, "success", False),
        (400, "none", False),
        (400, "unrelated", False),
        (400, "parser", False),
        (400, "guard-crash", False),
        (400, "unrelated-value-error", False),
        (200, "parser", False),
        (200, "envelope", False),
        (200, "raise", True),
        (400, "request-invalid", False),
        (400, "continue-success", False),
    ],
)
async def test_runner_distinguishes_published_errors_from_parser_crashes(
    collection, monkeypatch, tmp_path, status, behavior, passes
):
    from nodes.core.registry import NODE_REGISTRY
    from tests.conformance.verdict import verdict

    class Inputs(BaseModel):
        operation: Literal["create"]

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    collection["item"][0]["response"] = [
        {"code": status, "body": '{"error": "published failure"}', "header": []}
    ]
    seen = []

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, **kwargs):
            pass

        async def execute(self, data):
            async with httpx.AsyncClient() as client:
                response = await client.send(request(
                    json={"undocumented": 1} if behavior == "request-invalid" else {"data": {"name": "x"}}
                ))
                seen.append(response.status_code)
                if behavior in {"raise", "request-invalid"}:
                    if not 200 <= response.status_code < 300:
                        raise ValueError(f"Provider HTTP {response.status_code}")
                if behavior == "guard-crash" and response.status_code >= 400:
                    raise ValueError(response.json()["missing"])
                if behavior == "http-status":
                    response.raise_for_status()
                if behavior == "envelope":
                    return {"status": "error", "error": response.text}
                if behavior == "none":
                    return None
                if behavior == "unrelated":
                    raise RuntimeError("unrelated execution failure")
                if behavior == "unrelated-value-error":
                    raise ValueError("unrelated shape failure")
                if behavior == "parser":
                    return response.json()["missing"]
                if behavior == "continue-success":
                    collection["item"][0]["response"][0]["code"] = 200
                    await client.send(request(json={"data": {"name": "x"}}))
            return {"ok": True}

    monkeypatch.setitem(NODE_REGISTRY, "test-postman-errors", Node)
    monkeypatch.setitem(harness.PROVIDERS, "postman-errors", ("test-postman-errors", {}))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [collection])
    report = await harness.run_provider("postman-errors")
    assert seen == [status]
    assert report["fixture_errors"] == 0
    assert report["passed"] == int(passes)
    assert report["failed"] == int(not passes)
    (tmp_path / "manifest.json").write_text(json.dumps({"postman-errors": {"format": "postman"}}))
    result = verdict(report, tmp_path, False)
    assert result["state"] == ("postman-checked" if passes else "not-ready")

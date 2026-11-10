"""Scalar union and binary wire controls against the made-up fixture API."""
import copy

import httpx
import pytest
from jsonschema_path import SchemaPath
from openapi_core.validation.response.exceptions import InvalidData
from werkzeug.datastructures import MultiDict

from tests.conformance import harness
from tests.conformance.test_harness_gaps import response_contract
from tests.conformance.test_inputs import contract_for
from tests.conformance.test_schema_generation import scalar_parameter_contract


def parameter_request(value, location="query", style=None):
    path = "/items"
    if location == "path":
        path += "/" + ({"label": ".", "matrix": ";value="}.get(style, "")) + value
    return httpx.Request(
        "POST",
        "https://example.test" + path,
        params={"value": value} if location == "query" else None,
        headers={"value": value}
        if location == "header"
        else {"cookie": f"value={value}"}
        if location == "cookie"
        else None,
    )


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
@pytest.mark.parametrize(
    "location,style",
    [
        ("query", "form"),
        ("path", "simple"),
        ("header", "simple"),
        ("cookie", "form"),
        ("path", "label"),
        ("path", "matrix"),
    ],
)
@pytest.mark.parametrize("union", ["oneOf", "anyOf"])
def test_scalar_union_styles_validate_the_whole_schema(version, location, style, union):
    schema = {
        union: [
            {"type": "integer", "minimum": 2, "maximum": 4},
            {"type": "string", "pattern": "^[A-Z]+$"},
            {"type": "boolean"},
        ],
        "not": {"enum": [3, "DENY"]},
    }
    doc = scalar_parameter_contract(schema, location, style=style).doc
    doc["openapi"] = version
    original = copy.deepcopy(doc)
    contract = harness.Contract(doc)
    for value in ["2", "ABC", "true", "false"]:
        contract.validate_request(parameter_request(value, location, style))
    for value in ["3", "5", "DENY", "abc", "2.5"]:
        with pytest.raises(ValueError):
            contract.validate_request(parameter_request(value, location, style))
    assert doc == original


def test_union_casting_tries_members_until_original_schema_validates():
    schema = {
        "oneOf": [{"type": "number"}, {"type": "integer"}, {"type": "string"}],
        "pattern": "^[0-9]+$",
    }
    contract = scalar_parameter_contract(schema)
    root = SchemaPath.from_dict(contract.doc)
    path = root / "paths" / "/items" / "post" / "parameters" / 0 / "schema"
    decoder = contract.api.config.style_deserializers_factory.create(
        root, path, "form", False, "value"
    )
    # Number and integer candidates both violate oneOf; the string is valid.
    value = decoder.deserialize(MultiDict([("value", "2")]))
    assert value == "2" and isinstance(value, str)
    with pytest.raises(ValueError):
        contract.validate_request(parameter_request("ABC"))


def test_nested_union_references_keep_constraints_and_member_order():
    doc = scalar_parameter_contract(
        {
            "anyOf": [
                {"$ref": "#/components/schemas/Count"},
                {"oneOf": [{"type": "boolean"}, {"type": "string", "enum": ["ALL"]}]},
            ]
        }
    ).doc
    doc["components"] = {"schemas": {"Count": {"type": "integer", "minimum": 2}}}
    contract = harness.Contract(doc)
    for value in ["2", "true", "ALL"]:
        contract.validate_request(parameter_request(value))
    for value in ["all", "garbage"]:
        with pytest.raises(ValueError):
            contract.validate_request(parameter_request(value))


@pytest.mark.parametrize("union", ["oneOf", "anyOf"])
def test_same_scalar_type_union_keeps_parent_and_branch_constraints(union):
    contract = scalar_parameter_contract(
        {
            union: [
                {"type": "integer", "minimum": 2},
                {"type": "integer", "maximum": 0},
            ],
            "not": {"enum": [4]},
        }
    )
    for value in ["0", "2"]:
        contract.validate_request(parameter_request(value))
    for value in ["1", "4", "x"]:
        with pytest.raises(ValueError):
            contract.validate_request(parameter_request(value))


@pytest.mark.parametrize(
    "schema",
    [
        {
            "oneOf": [
                {"type": "integer"},
                {"type": "array", "items": {"type": "integer"}},
            ]
        },
        {"anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "string"}}]},
        {"anyOf": [{"type": "string"}, {}]},
    ],
)
def test_ambiguous_union_keeps_existing_fixture_error(schema):
    contract = scalar_parameter_contract(schema)
    with pytest.raises(
        harness.FixtureError,
        match="Ambiguous parameter serialization for untyped union",
    ):
        contract.validate_request(parameter_request("1"))


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
def test_untyped_json_body_unions_are_not_parameter_cast(version):
    doc = contract_for({"oneOf": [{"type": "integer"}, {"type": "boolean"}]}).doc
    doc["openapi"] = version
    contract = harness.Contract(doc)
    for value in [1, True]:
        contract.validate_request(
            httpx.Request("POST", "https://example.test/items", json=value)
        )
    for value in ["1", "true", {}, []]:
        with pytest.raises(ValueError):
            contract.validate_request(
                httpx.Request("POST", "https://example.test/items", json=value)
            )


def multipart_contract(version, *, array=False, encoding=None):
    doc = contract_for({}).doc
    doc["openapi"] = version
    binary = {"type": "string", "format": "binary"}
    schema = {
        "type": "object",
        "required": ["file", "count", "metadata", "caption"],
        "properties": {
            "file": {"type": "array", "items": binary} if array else binary,
            "count": {"type": "integer", "minimum": 2},
            "caption": {"type": "string", "enum": ["café"]},
            "metadata": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string", "enum": ["fixture"]}},
            },
        },
    }
    media = {
        "schema": schema,
        "encoding": {"count": {"style": "form"}, **(encoding or {})},
    }
    doc["paths"]["/items"]["post"]["requestBody"]["content"] = {
        "multipart/form-data": media
    }
    return harness.Contract(doc)


def multipart_request(parts=(), count="2", metadata='{"name":"fixture"}'):
    request = httpx.Request(
        "POST",
        "https://example.test/items",
        files=[
            *parts,
            ("count", (None, count)),
            ("caption", (None, b"caf\xe9", "text/plain; charset=iso-8859-1")),
            ("metadata", (None, metadata, "application/json; charset=utf-8")),
        ],
    )
    request.read()
    return request


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
@pytest.mark.parametrize(
    "media", ["image/png", "application/pdf", "text/plain; charset=utf-8"]
)
def test_multipart_preserves_binary_bytes_and_part_content_types(version, media):
    contract = multipart_contract(version)
    payload = b"\x00\xff\r\n\x80\nfixture\r\n"
    request = multipart_request([("file", ("fixture.bin", payload, media))])
    original = request.content
    contract.validate_request(request)
    raw_parts = harness.multipart_loads(
        request.content,
        boundary=request.headers["content-type"].split("boundary=", 1)[1],
    )
    assert raw_parts["file"].data == payload
    assert raw_parts["file"].content_type == media
    assert request.content == original
    for invalid in [
        multipart_request(),
        multipart_request([("file", ("f", payload, media))], count="1"),
        multipart_request(
            [("file", ("f", payload, media))], metadata='{"name":"wrong"}'
        ),
    ]:
        with pytest.raises(ValueError):
            contract.validate_request(invalid)


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
def test_repeated_binary_parts_and_encoding_media_constraints(version):
    contract = multipart_contract(
        version,
        array=True,
        encoding={
            "file": {"contentType": "image/png, application/pdf"},
        },
    )
    parts = [
        ("file", ("a.png", b"\xff\x00", "image/png")),
        ("file", ("b.pdf", b"\x80\r\n", "application/pdf")),
    ]
    request = multipart_request(parts)
    contract.validate_request(request)
    parts[1] = ("file", ("b.txt", b"text", "text/plain"))
    with pytest.raises(ValueError, match="Content-Type"):
        contract.validate_request(multipart_request(parts))


@pytest.mark.parametrize("binary", [True, False])
def test_binary_response_compatibility_is_scoped_and_keeps_constraints(
    monkeypatch, binary
):
    monkeypatch.setattr(harness, "FULL", True)
    schema = {
        "type": "string",
        "minLength": 2,
        "maxLength": 4,
        **({"format": "binary"} if binary else {}),
    }
    contract, request, op = response_contract(
        {"application/octet-stream": {"schema": schema}}, version="3.1.0"
    )
    for payload in [b"\x00\xff", b"x", b"12345"]:
        response = httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/octet-stream"},
            request=request,
        )
        if binary and len(payload) == 2:
            contract.api.validate_response(
                contract.adapter(request), harness.response_adapter(response)
            )
        else:
            with pytest.raises(InvalidData):
                contract.api.validate_response(
                    contract.adapter(request), harness.response_adapter(response)
                )


def test_multipart_boundary_keeps_its_case():
    contract = multipart_contract("3.1.0")
    request = multipart_request(
        [("file", ("fixture.bin", b"\x00\xff", "application/octet-stream"))]
    )
    old_boundary = request.headers["content-type"].split("boundary=", 1)[1]
    boundary = "ConformanceBoundaryAbCdEf"
    request = httpx.Request(
        "POST",
        str(request.url),
        content=request.content.replace(old_boundary.encode(), boundary.encode()),
        headers={"content-type": f'multipart/form-data; boundary="{boundary}"'},
    )
    contract.validate_request(request)

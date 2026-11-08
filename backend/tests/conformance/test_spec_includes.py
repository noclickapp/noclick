"""Pinned multi-file contracts stay offline and preserve request constraints."""
import copy
import hashlib
import json

import httpx
import pytest

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for


SOURCE = "https://provider.example.test/api/openapi.yaml"


def pin(tmp_path, filename, content, source):
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "file": filename,
        "sha256": hashlib.sha256(content).hexdigest(),
        "source_url": source,
    }


def catalog(tmp_path, monkeypatch, ref="./schema.yaml#/Item", *, multi=False):
    doc = copy.deepcopy(contract_for({"$ref": ref}).doc)
    doc["info"]["description"] = {"$ref": "./intro.md"}
    includes = [
        pin(
            tmp_path,
            "includes/schema.yaml",
            b"Item:\n  type: object\n  required: [count]\n  properties:\n    count: {type: integer, minimum: 2}\n",
            "https://provider.example.test/api/schema.yaml",
        ),
        pin(
            tmp_path,
            "includes/intro.md",
            b"Official **API** documentation.\n",
            "https://provider.example.test/api/intro.md",
        ),
    ]
    entry = {
        **pin(tmp_path, "openapi.json", json.dumps(doc).encode(), SOURCE),
        "version": "1",
        "includes": includes,
    }
    manifest = {"test": {"specs": [entry]} if multi else entry}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    return doc, entry


def save(tmp_path, entry):
    (tmp_path / "manifest.json").write_text(json.dumps({"test": entry}))


def request(body):
    return httpx.Request("POST", "https://example.test/items", json=body)


@pytest.mark.parametrize("multi", [False, True])
def test_pinned_schema_and_description_validate_requests(tmp_path, monkeypatch, multi):
    doc, entry = catalog(tmp_path, monkeypatch, multi=multi)
    before = (tmp_path / entry["file"]).read_bytes()
    (loaded,) = harness.load_specs("test")
    assert loaded["info"]["description"] == "Official **API** documentation.\n"
    contract = harness.Contract(loaded)
    contract.validate_request(request({"count": 2}))
    for body in ({"count": 1}, {"count": "2"}, {}):
        with pytest.raises(Exception):
            contract.validate_request(request(body))
    assert (tmp_path / entry["file"]).read_bytes() == before
    assert doc["info"]["description"] == {"$ref": "./intro.md"}


@pytest.mark.parametrize(
    "ref",
    [
        "missing.yaml#/Item",
        "../outside.yaml#/Item",
        "./openapi.yaml#/Item",
        "https://provider.example.test/api/schema.yaml#/Item",
        "http://provider.example.test/api/schema.yaml#/Item",
        "//provider.example.test/api/schema.yaml#/Item",
        "/api/schema.yaml#/Item",
        "file:includes/schema.yaml#/Item",
        "#components/schemas/Item",
        "schema.yaml?untrusted=1#/Item",
        "..\\schema.yaml#/Item",
    ],
)
def test_unpinned_or_nonrelative_refs_are_refused(tmp_path, monkeypatch, ref):
    catalog(tmp_path, monkeypatch, ref)
    with pytest.raises(ValueError, match="Remote references are forbidden"):
        harness.load_spec("test")


def test_include_hash_mismatch_is_refused(tmp_path, monkeypatch):
    _, entry = catalog(tmp_path, monkeypatch)
    (tmp_path / entry["includes"][0]["file"]).write_text("Item: {}")
    with pytest.raises(ValueError, match="include hash differs"):
        harness.load_spec("test")


def test_include_source_must_equal_resolved_ref_url(tmp_path, monkeypatch):
    _, entry = catalog(tmp_path, monkeypatch)
    entry["includes"][0][
        "source_url"
    ] = "https://different.example.test/api/schema.yaml"
    save(tmp_path, entry)
    with pytest.raises(ValueError, match="source_url mismatch"):
        harness.load_spec("test")


@pytest.mark.parametrize("escape", ["../outside.yaml", "absolute", "symlink"])
def test_include_cannot_escape_catalog(tmp_path, monkeypatch, escape):
    _, entry = catalog(tmp_path, monkeypatch, "../outside.yaml#/Item")
    outside = tmp_path.parent / "outside.yaml"
    outside.write_bytes((tmp_path / entry["includes"][0]["file"]).read_bytes())
    if escape == "absolute":
        escape = str(outside)
    elif escape == "symlink":
        (tmp_path / escape).symlink_to(outside)
    entry["includes"][0].update(
        file=escape, source_url="https://provider.example.test/outside.yaml"
    )
    save(tmp_path, entry)
    with pytest.raises(ValueError, match="escapes catalog"):
        harness.load_spec("test")


def test_main_spec_cannot_escape_catalog(tmp_path, monkeypatch):
    _, entry = catalog(tmp_path, monkeypatch)
    outside = tmp_path.parent / "outside.json"
    outside.write_bytes((tmp_path / entry["file"]).read_bytes())
    entry["file"] = "../outside.json"
    save(tmp_path, entry)
    with pytest.raises(ValueError, match="escapes catalog"):
        harness.load_spec("test")


def test_nested_refs_use_included_source_and_handle_cycles(tmp_path, monkeypatch):
    _, entry = catalog(tmp_path, monkeypatch, "./schemas/item.yaml#/Item")
    entry["includes"][0] = pin(
        tmp_path,
        "includes/item.yaml",
        b"""
Item:
  type: object
  required: [count]
  properties:
    count: {$ref: '../types.yaml#/a~1b~0c/0'}
    child: {$ref: '#/Item'}
""",
        "https://provider.example.test/api/schemas/item.yaml",
    )
    entry["includes"].append(
        pin(
            tmp_path,
            "includes/types.yaml",
            b"""
a/b~c:
  - {type: integer, minimum: 2}
""",
            "https://provider.example.test/api/types.yaml",
        )
    )
    save(tmp_path, entry)
    loaded = harness.load_spec("test")
    contract = harness.Contract(loaded)
    contract.validate_request(request({"count": 2, "child": {"count": 3}}))
    with pytest.raises(Exception):
        contract.validate_request(request({"count": 2, "child": {"count": 1}}))
    assert json.loads(json.dumps(loaded)) == loaded


def test_nested_unpinned_ref_is_refused(tmp_path, monkeypatch):
    _, entry = catalog(tmp_path, monkeypatch)
    entry["includes"][0] = pin(
        tmp_path,
        "includes/schema.yaml",
        b"Item: {$ref: other.yaml#/Item}",
        entry["includes"][0]["source_url"],
    )
    save(tmp_path, entry)
    with pytest.raises(ValueError, match="unpinned relative reference"):
        harness.load_spec("test")


@pytest.mark.parametrize("fragment", ["#not/a/pointer", "#/Item~2", "#/items/-1"])
def test_invalid_included_pointers_are_refused(tmp_path, monkeypatch, fragment):
    catalog(tmp_path, monkeypatch, "schema.yaml" + fragment)
    with pytest.raises((ValueError, KeyError)):
        harness.load_spec("test")


def test_cycle_across_files_and_reference_back_to_main(tmp_path, monkeypatch):
    doc, entry = catalog(tmp_path, monkeypatch)
    doc["components"] = {"schemas": {"Count": {"type": "integer", "minimum": 2}}}
    raw = json.dumps(doc).encode()
    entry.update(pin(tmp_path, entry["file"], raw, SOURCE))
    entry["includes"].append(
        {key: entry[key] for key in ("file", "sha256", "source_url")}
    )
    entry["includes"][0] = pin(
        tmp_path,
        "includes/schema.yaml",
        b"""
Item:
  type: object
  required: [count]
  properties:
    count: {$ref: 'openapi.yaml#/components/schemas/Count'}
    child: {$ref: 'other.yaml#/Other'}
""",
        "https://provider.example.test/api/schema.yaml",
    )
    entry["includes"].append(
        pin(
            tmp_path,
            "includes/other.yaml",
            b"""
Other:
  type: object
  properties:
    child: {$ref: 'schema.yaml#/Item'}
""",
            "https://provider.example.test/api/other.yaml",
        )
    )
    save(tmp_path, entry)
    loaded = harness.load_spec("test")
    contract = harness.Contract(loaded)
    contract.validate_request(request({"count": 2, "child": {"child": {"count": 3}}}))
    with pytest.raises(Exception):
        contract.validate_request(
            request({"count": 2, "child": {"child": {"count": 1}}})
        )
    assert json.loads(json.dumps(loaded)) == loaded


@pytest.mark.parametrize(
    "change",
    [
        {"source_url": "file:///schema.yaml"},
        {"source_url": "https://provider.example.test/api/schema.yaml#fragment"},
        {"sha256": "wrong"},
    ],
)
def test_invalid_include_pins_fail_closed(tmp_path, monkeypatch, change):
    _, entry = catalog(tmp_path, monkeypatch)
    entry["includes"][0].update(change)
    save(tmp_path, entry)
    with pytest.raises(ValueError):
        harness.load_spec("test")


def test_network_ref_inside_include_is_refused(tmp_path, monkeypatch):
    _, entry = catalog(tmp_path, monkeypatch)
    entry["includes"][0] = pin(
        tmp_path,
        "includes/schema.yaml",
        b"Item: {$ref: 'https://provider.example.test/api/other.yaml#/Item'}",
        entry["includes"][0]["source_url"],
    )
    save(tmp_path, entry)
    with pytest.raises(ValueError, match="Remote references are forbidden"):
        harness.load_spec("test")


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
def test_reference_siblings_match_local_reference_validation(
    tmp_path, monkeypatch, version
):
    doc, entry = catalog(tmp_path, monkeypatch)
    doc["openapi"] = version
    schema = doc["paths"]["/items"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    schema["required"] = ["extra"]
    entry.update(pin(tmp_path, entry["file"], json.dumps(doc).encode(), SOURCE))
    save(tmp_path, entry)
    loaded = harness.load_spec("test")
    bundled_schema = loaded["paths"]["/items"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert bundled_schema["required"] == ["extra"]
    assert bundled_schema["$ref"].startswith("#/")
    local = copy.deepcopy(loaded)
    local["components"] = {"schemas": {"Item": harness.resolve(loaded, bundled_schema)}}
    local["paths"]["/items"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"] = "#/components/schemas/Item"
    contracts = [harness.Contract(document) for document in (loaded, local)]

    def accepts(contract, body):
        try:
            contract.validate_request(request(body))
        except Exception:
            return False
        return True

    for body in (
        {"count": 2, "extra": True},
        {"count": 2},
        {"count": 1, "extra": True},
    ):
        assert accepts(contracts[0], body) == accepts(contracts[1], body)
    assert accepts(contracts[0], {"count": 2, "extra": True})
    assert not accepts(contracts[0], {"count": 1, "extra": True})


def test_text_include_cannot_be_used_as_a_schema_after_description_caching(
    tmp_path, monkeypatch
):
    catalog(tmp_path, monkeypatch, "./intro.md")
    with pytest.raises(
        ValueError, match="Text includes are only allowed for descriptions"
    ):
        harness.load_spec("test")

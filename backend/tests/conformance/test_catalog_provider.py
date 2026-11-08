"""A provider run from a catalog on disk: pins, the reviewed-findings ratchet, reruns.

`fixtures/catalog` is a made-up API and node written for these tests. Real
providers' specs are never vendored; CONFORMANCE_CATALOG supplies them.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Union

import httpx
import pytest
from pydantic import BaseModel, Field

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for

CATALOG = Path(__file__).with_name("fixtures") / "catalog"
BACKEND = Path(__file__).parents[2]


class ListItems(BaseModel):
    operation: Literal["list_items"]
    limit: int = 10


class SearchItems(BaseModel):
    operation: Literal["search_items"]
    q: str


class CreateItem(BaseModel):
    operation: Literal["create_item"]
    name: str


class ResizeItem(BaseModel):
    operation: Literal["resize_item"]
    item_id: str
    size: str  # The spec wants an integer: the reviewed finding.


class OnItemCreated(BaseModel):
    operation: Literal["on_item_created"]


class FixtureConfig(BaseModel):
    config: Union[ListItems, SearchItems, CreateItem, ResizeItem, OnItemCreated] = Field(
        discriminator="operation"
    )
    credentials: dict


class FixtureNode:
    scope_registry = None
    get_config_model = staticmethod(lambda: FixtureConfig)

    def __init__(self, config, **kwargs):
        self.config = config

    async def execute(self, data):
        c = self.config.config
        headers = {"Authorization": f"Bearer {self.config.credentials['token']}"}
        async with httpx.AsyncClient(
            base_url="https://api.fixture.example/v1", headers=headers
        ) as client:
            if c.operation == "list_items":
                response = await client.get("/items", params={"limit": c.limit})
            elif c.operation == "search_items":
                response = await client.get("/items/search", params={"q": c.q})
            elif c.operation == "create_item":
                response = await client.post("/items", json={"name": c.name})
            else:
                response = await client.patch(f"/items/{c.item_id}", json={"size": c.size})
        response.raise_for_status()
        return response.json()


@pytest.fixture
def fixture_catalog(monkeypatch):
    """The fixture catalog, as CONFORMANCE_CATALOG would load it."""
    from nodes.core.registry import NODE_REGISTRY

    entry = json.loads((CATALOG / "manifest.json").read_text())["fixture"]
    monkeypatch.setitem(NODE_REGISTRY, "test-fixture", FixtureNode)
    monkeypatch.setattr(harness, "CATALOG", CATALOG)
    monkeypatch.setitem(harness.PROVIDERS, "fixture", (entry["node_type"], entry["credential"]))
    monkeypatch.setattr(harness, "INPUTS", json.loads((CATALOG / "inputs.json").read_text()))
    monkeypatch.setattr(
        harness, "WITNESSES", json.loads((CATALOG / "witnesses.json").read_text())
    )


INVALID_SIZE = (
    "Value {'size': '1'} not valid for schema of type object: "
    "(<ValidationError: \"'1' is not of type 'integer'\">,)"
)
BASE = "https://api.fixture.example/v1"
# What a reviewer accepted: each operation's config, requests and findings.
REVIEWED = {
    "list_items": {
        "skipped": None,
        "passed": True,
        "config": {"limit": 25, "operation": "list_items"},
        "requests": [("GET", f"{BASE}/items?limit=25", "", "GET /items")],
        "failures": [],
    },
    "search_items": {
        "skipped": None,
        "passed": True,
        # Enriched: the generated "1" is shorter than the spec's minLength.
        "config": {"q": "111", "operation": "search_items"},
        "requests": [("GET", f"{BASE}/items/search?q=111", "", "GET /items/search")],
        "failures": [],
    },
    "create_item": {
        "skipped": None,
        "passed": True,
        "config": {"name": "111", "operation": "create_item"},
        "requests": [("POST", f"{BASE}/items", '{"name":"111"}', "POST /items")],
        "failures": [],
    },
    "resize_item": {
        "skipped": None,
        "passed": False,
        "config": {"item_id": "1", "size": "1", "operation": "resize_item"},
        "requests": [("PATCH", f"{BASE}/items/1", '{"size":"1"}', "PATCH /items/{item_id}")],
        "failures": [
            f"request: InvalidRequestBody: Request body validation error: {INVALID_SIZE}"
            f" / InvalidSchemaValue: {INVALID_SIZE}"
        ],
    },
    "on_item_created": {
        "skipped": "trigger passthrough",
        "passed": False,
        "config": {},
        "requests": [],
        "failures": [],
    },
}


async def test_catalog_provider_has_no_new_findings(fixture_catalog):
    report = await harness.run_provider("fixture")
    assert report["fixture_errors"] == 0, report
    assert {op["operation"] for op in report["operations"]} == set(REVIEWED)
    for op in report["operations"]:
        prior = REVIEWED[op["operation"]]
        assert op["skipped"] == prior["skipped"]
        assert not op["fixture_errors"], op
        assert op["config"] == prior["config"]
        if op["passed"] == prior["passed"]:
            assert [
                (r["method"], r["url"], r["body"], r["spec_operation"])
                for r in op["requests"]
            ] == prior["requests"], op
            assert all(r["auth_placement"] == "header" for r in op["requests"]), op
        assert set(op["failures"]) <= set(prior["failures"]), op
        if not op["skipped"] and not op["failures"]:
            assert op["passed"] and op["requests"], op
            assert all("response_sha256" in req for req in op["requests"]), op
    assert report["coverage"] == {"implemented": 4, "total": 4}
    assert report["auth_checked"] == 4


def test_catalog_pins_its_spec_by_hash_and_version(fixture_catalog, tmp_path, monkeypatch):
    entry = harness.spec_entry("fixture")[1]
    doc = harness.load_spec("fixture")
    assert len(entry["sha256"]) == 64
    assert doc["info"]["version"] == entry["version"]
    for change, error in (
        ({"sha256": "0" * 64}, "hash differs"),
        ({"version": "2026-02-02.fixture"}, "version differs"),
    ):
        (tmp_path / "fixture.yaml").write_bytes((CATALOG / "fixture.yaml").read_bytes())
        (tmp_path / "manifest.json").write_text(json.dumps({"fixture": {**entry, **change}}))
        monkeypatch.setattr(harness, "CATALOG", tmp_path)
        with pytest.raises(ValueError, match=error):
            harness.load_spec("fixture")


def test_modified_spec_and_remote_refs_fail_closed(tmp_path, monkeypatch):
    spec = {"info": {"version": "1"}, "$ref": "https://example.test/spec.json"}
    raw = json.dumps(spec).encode()
    (tmp_path / "test.json").write_bytes(raw)
    manifest = {"test": {"file": "test.json", "version": "1", "sha256": "wrong"}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(harness, "CATALOG", tmp_path)
    with pytest.raises(ValueError, match="hash differs"):
        harness.load_spec("test")
    manifest["test"]["sha256"] = harness.hashlib.sha256(raw).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Remote references"):
        harness.load_spec("test")


def test_specs_come_only_from_the_catalog(monkeypatch):
    monkeypatch.setattr(harness, "CATALOG", None)
    with pytest.raises(ValueError, match="CONFORMANCE_CATALOG"):
        harness.load_spec("fixture")
    monkeypatch.setattr(harness, "CATALOG", CATALOG)
    with pytest.raises(ValueError, match="not in the catalog"):
        harness.spec_entry("unlisted")


def harness_process(*args, catalog=None, code=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CONFORMANCE_")}
    if catalog:
        env["CONFORMANCE_CATALOG"] = str(catalog)
    return subprocess.run(
        [sys.executable, *(["-c", code] if code else ["-m", "tests.conformance.harness"]), *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120,
    )


def test_conformance_catalog_names_every_provider_input_and_witness():
    loaded = harness_process(catalog=CATALOG, code=(
        "import json; from tests.conformance import harness as h; print(json.dumps("
        "[h.PROVIDERS, sorted(h.INPUTS), sorted(h.WITNESSES), str(h.spec_entry('fixture')[0])]))"
    ))
    assert loaded.returncode == 0, loaded.stderr
    providers, inputs, witnesses, base = json.loads(loaded.stdout)
    assert providers == {
        "fixture": ["test-fixture", {"credential_type": "fixture_token", "token": "<token>"}]
    }
    assert inputs == ["list_items"] and witnesses == ["GET /items"]
    assert base == str(CATALOG)
    refused = harness_process("--output", os.devnull)
    assert refused.returncode == 2
    assert "set CONFORMANCE_CATALOG" in refused.stderr


async def test_stripe_probes_send_the_pinned_api_version(monkeypatch):
    from nodes.core.registry import NODE_REGISTRY

    class Read(BaseModel):
        operation: Literal["read"]

    class Config(BaseModel):
        config: Read
        credentials: dict

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, config, **kwargs):
            self.credentials = config.credentials

        async def execute(self, data):
            version = self.credentials.get("stripe_version")
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://example.test/items",
                    json={},
                    headers={"Stripe-Version": version} if version else {},
                )
            return {"ok": True}

    doc = contract_for({"type": "object"}).doc
    monkeypatch.setitem(NODE_REGISTRY, "test-versioned", Node)
    monkeypatch.setattr(harness, "load_specs", lambda _: [doc])
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "INPUTS", {})
    for provider in ("stripe", "other"):
        monkeypatch.setitem(harness.PROVIDERS, provider, ("test-versioned", {}))
    stripe = await harness.run_provider("stripe")
    requests = [r for op in stripe["operations"] for r in op["requests"]]
    assert requests and all(r["api_version"] == doc["info"]["version"] for r in requests)
    other = await harness.run_provider("other")
    assert all("api_version" not in r for op in other["operations"] for r in op["requests"])


def test_socket_escape_is_forbidden():
    import socket

    with socket.socket() as connection, pytest.raises(
        AssertionError, match="Network forbidden"
    ):
        connection.connect(("127.0.0.1", 9))


async def test_input_generator_failure_cannot_disappear_during_other_enrichments(
    fixture_catalog, monkeypatch
):
    # Unbroken, both enrichments rerun to a pass, so a rerun was on offer.
    report = await harness.run_provider("fixture")
    rows = {op["operation"]: op for op in report["operations"]}
    assert report["fixture_errors"] == 0
    assert rows["search_items"]["passed"] and rows["create_item"]["passed"]

    original = harness.enrich_config

    def broken(contract, member, config, requests):
        if config["operation"] == "search_items":
            raise ValueError("unsupported input witness")
        return original(contract, member, config, requests)

    monkeypatch.setattr(harness, "enrich_config", broken)
    report = await harness.run_provider("fixture")
    assert report["fixture_errors"] == 1
    row = next(op for op in report["operations"] if op["operation"] == "search_items")
    assert "unsupported input witness" in row["fixture_errors"][0]

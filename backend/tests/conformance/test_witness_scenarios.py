"""Keep independent documentation scenarios separate without forgiving bad IDs."""
import copy
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for


def response_contract():
    doc = copy.deepcopy(contract_for({}).doc)
    doc["paths"]["/items"]["post"]["responses"]["200"]["content"] = {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            }
        }
    }
    return harness.Contract(doc)


def test_query_witnesses_match_decoded_exact_multimaps(monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    monkeypatch.setattr(
        harness,
        "WITNESSES",
        {
            "POST /items": {"body": {"id": "fallback"}},
            "POST /items?": {"body": {"id": "unfiltered"}},
            "POST /items?account_id=a%2Fb&tag=x&tag=y&empty=": {
                "body": {"id": "filtered"},
                "source": "https://example.test/docs",
                "headers": {"X-Witness": "filtered"},
            },
        },
    )
    contract = response_contract()
    for query, expected in [
        ("", "unfiltered"),
        ("?tag=y&account_id=a%2fb&empty=&tag=x", "filtered"),
        ("?account_id=a%252Fb&tag=x&tag=y&empty=", "fallback"),
        ("?account_id=a%2Fb&tag=x&empty=", "fallback"),
        ("?account_id=a%2Fb&tag=x&tag=y&tag=y&empty=", "fallback"),
        ("?account_id=a%2Fb&tag=x&tag=y", "fallback"),
    ]:
        request = httpx.Request("POST", "https://example.test/items" + query, json={})
        contract.validate_request(request)
        record = {}
        response = contract.response(
            request, contract.match(request)[2], key="POST /items", record=record
        )
        assert response.json() == {"id": expected}
        assert record["response_source"] == "docs"
        if expected == "filtered":
            assert response.headers["X-Witness"] == "filtered"
            assert record["response_source_url"] == "https://example.test/docs"
            assert "?account_id=" in record["response_witness"]


def test_ambiguous_or_invalid_query_witness_is_a_fixture_error(monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    contract = response_contract()
    request = httpx.Request("POST", "https://example.test/items?a=1&b=2", json={})
    monkeypatch.setattr(
        harness,
        "WITNESSES",
        {
            "POST /items?a=1&b=2": {"body": {"id": "a"}},
            "POST /items?b=2&a=1": {"body": {"id": "b"}},
        },
    )
    with pytest.raises(harness.FixtureError, match="Ambiguous query witnesses"):
        contract.response(request, contract.match(request)[2], key="POST /items")
    harness.WITNESSES.pop("POST /items?b=2&a=1")
    harness.WITNESSES["POST /items?a=1&b=2"]["body"] = {"id": 123}
    with pytest.raises(harness.FixtureError, match="Invalid documented witness"):
        contract.response(request, contract.match(request)[2], key="POST /items")


@pytest.mark.parametrize("wrong_identity", [False, True])
@pytest.mark.parametrize(
    "overrides", [None, {"get-alpha": {"operation": "get", "resource_id": "alpha"}}]
)
async def test_documented_scenarios_are_isolated_and_still_check_ancestry(
    monkeypatch,
    wrong_identity,
    overrides,
):
    from nodes.core.registry import NODE_REGISTRY

    class Inputs(BaseModel):
        operation: Literal["get"]
        resource_id: str

    class Config(BaseModel):
        config: Inputs
        credentials: dict

    seen = []

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, *, config, **kwargs):
            self.config = config

        async def execute(self, data):
            selected = self.config.config.resource_id
            seen.append((selected, self.config.credentials.copy()))
            assert self.config.credentials["account"] == selected
            async with httpx.AsyncClient() as client:
                for path in ["/items", "/items/{id}"]:
                    result = await client.post(
                        "https://example.test" + path.replace("{id}", selected),
                        json={},
                    )
                    if result.json()["id"] != selected:
                        raise ValueError("resource ancestry mismatch")
            return {"ok": True}

    contract = response_contract()
    contract.doc["paths"]["/items/{id}"] = copy.deepcopy(
        contract.doc["paths"]["/items"]
    )
    contract.doc["paths"]["/items/{id}"]["post"]["parameters"] = [
        {
            "in": "path",
            "name": "id",
            "required": True,
            "schema": {"type": "string"},
        }
    ]
    witnesses, inputs = {}, {}
    for identity in ["alpha", "beta"]:
        witnesses[identity] = {
            "body": {"id": identity},
            "source": f"https://example.test/docs/{identity}",
        }
        inputs["get-" + identity] = {
            "operation": "get",
            "config": {"resource_id": identity},
            "source": f"https://example.test/docs/{identity}",
            "credential": {"account": identity, "token": "<token>"},
            "witnesses": {
                "POST /items": identity,
                "POST /items/{id}": "beta" if wrong_identity else identity,
            },
        }
    prior = copy.deepcopy((witnesses, inputs))
    monkeypatch.setattr(harness, "FULL", True)
    monkeypatch.setattr(harness, "WITNESSES", witnesses)
    monkeypatch.setattr(harness, "INPUTS", inputs)
    monkeypatch.setitem(NODE_REGISTRY, "test-scenarios", Node)
    monkeypatch.setitem(
        harness.PROVIDERS, "scenarios", ("test-scenarios", {"account": "default"})
    )
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, {}))
    monkeypatch.setattr(harness, "load_specs", lambda _: [contract.doc])
    report = await harness.run_provider("scenarios", config_overrides=overrides)
    assert report["checked"] == 2
    assert report["passed"] == (1 if wrong_identity else 2)
    assert report["fixture_errors"] == 0
    assert [r["scenario"] for r in report["operations"]] == ["get-alpha", "get-beta"]
    assert [s[0] for s in seen] == ["alpha", "beta"]
    assert all(c["token"] == harness.TOKEN for _, c in seen)
    assert prior == (witnesses, inputs)
    if wrong_identity:
        assert "resource ancestry mismatch" in report["operations"][0]["failures"][0]


def test_scenarios_fail_closed_for_missing_or_invalid_supporting_witnesses(monkeypatch):
    monkeypatch.setattr(harness, "FULL", True)
    monkeypatch.setattr(
        harness,
        "WITNESSES",
        {
            "global": {
                "body": {"id": "unrelated"},
                "source": "https://example.test/docs",
            },
        },
    )
    harness.WITNESSES["POST /items"] = harness.WITNESSES["global"]
    assert harness.scenario_witnesses({"witnesses": {}}) == {}
    with pytest.raises(harness.FixtureError, match="Unknown scenario witness"):
        harness.scenario_witnesses({"witnesses": {"POST /items": "missing"}})
    harness.WITNESSES["global"]["source"] = "file:///tmp/example"
    with pytest.raises(harness.FixtureError, match="documentation URL"):
        harness.scenario_witnesses({"witnesses": {"POST /items": "global"}})
    contract = response_contract()
    request = httpx.Request("POST", "https://example.test/items", json={})
    for witnesses, error in [
        ({}, "no witness"),
        ({"POST /items": {"body": {"id": 3}}}, "Invalid documented witness"),
    ]:
        with pytest.raises(harness.FixtureError, match=error):
            contract.response(
                request,
                contract.match(request)[2],
                key="POST /items",
                witnesses=witnesses,
                strict_witnesses=True,
            )

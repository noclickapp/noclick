"""Catalog credentials select a family without changing contract checks."""
import copy
from typing import Annotated, Literal, Union

import httpx
import pytest
from pydantic import BaseModel, Field, model_validator

from tests.conformance import harness
from tests.conformance.test_inputs import contract_for


def test_single_credential_and_exact_operation_overrides():
    default = {"credential_type": "project", "token": "<token>", "region": "eu"}
    entry = {
        "credentials": {"account": {"credential_type": "account", "secret": "<token>"}},
        "operation_credentials": {"manage": "account"},
    }
    original = copy.deepcopy(entry)
    selected = harness.operation_credentials(entry, ["send", "manage"], default)
    assert selected == {
        "send": {"credential_type": "project", "token": harness.TOKEN, "region": "eu"},
        "manage": {"credential_type": "account", "secret": harness.TOKEN},
    }
    selected["manage"]["secret"] = "changed"
    assert entry == original and default["token"] == "<token>"
    assert harness.operation_credentials({}, ["send", "manage"], default) == {
        op: {**default, "token": harness.TOKEN} for op in ["send", "manage"]
    }


@pytest.mark.parametrize(
    "entry, default, message",
    [
        ({"credentials": []}, {}, "credentials must map"),
        ({"credentials": {"account": "<token>"}}, {}, "credentials must map"),
        ({"operation_credentials": []}, {}, "operation_credentials must"),
        ({"operation_credentials": {"typo": "account"}}, {}, "Unknown catalog credential operation"),
        ({"operation_credentials": {"send": "missing"}}, {}, "Unknown catalog credential for"),
        ({"operation_credentials": {"send": []}}, {}, "Unknown catalog credential for"),
        ({"credentials": {"account": {}}}, None, "No catalog credential configured"),
    ],
)
def test_invalid_credential_mappings_fail_closed(entry, default, message):
    with pytest.raises(ValueError, match=message):
        harness.operation_credentials(entry, ["send"], default)


@pytest.mark.parametrize("named_only", [False, True])
@pytest.mark.parametrize("mutation", [None, "wrong_credential", "wrong_header"])
async def test_runner_selects_credentials_including_enrichment(monkeypatch, named_only, mutation):
    from nodes.core.registry import NODE_REGISTRY

    class Send(BaseModel):
        operation: Literal["send"]
        value: str | None = None

    class Manage(BaseModel):
        operation: Literal["manage"]
        value: str | None = None

    class Project(BaseModel):
        credential_type: Literal["project"]
        token: str

    class Account(BaseModel):
        credential_type: Literal["account"]
        secret: str

    class Config(BaseModel):
        config: Annotated[Union[Send, Manage], Field(discriminator="operation")]
        credentials: Annotated[Union[Project, Account], Field(discriminator="credential_type")]

        @model_validator(mode="after")
        def family(self):
            expected = "project" if self.config.operation == "send" else "account"
            if self.credentials.credential_type != expected:
                raise ValueError("Wrong credential family")
            return self

    attempts = []

    class Node:
        scope_registry = None
        get_config_model = staticmethod(lambda: Config)

        def __init__(self, *, config, **kwargs):
            self.config = config

        async def execute(self, data):
            config, credential = self.config.config, self.config.credentials
            attempts.append((config.operation, credential.credential_type, config.value))
            header = "X-Project-Token" if config.operation == "send" else "X-Account-Token"
            if mutation == "wrong_header" and config.operation == "manage":
                header = "X-Wrong-Token"
            token = credential.token if isinstance(credential, Project) else credential.secret
            assert token == harness.TOKEN
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://example.test/{config.operation}",
                    headers={header: token},
                    json={"value": config.value} if config.value else {},
                )
            return {"ok": True}

    doc = contract_for({
        "type": "object", "required": ["value"],
        "properties": {"value": {"type": "string"}},
    }).doc
    item = doc["paths"].pop("/items")
    doc["components"] = {"securitySchemes": {}}
    for op, family in [("send", "Project"), ("manage", "Account")]:
        doc["paths"]["/" + op] = copy.deepcopy(item)
        doc["paths"]["/" + op]["post"]["security"] = [{family: []}]
        doc["components"]["securitySchemes"][family] = {
            "type": "apiKey", "in": "header", "name": f"X-{family}-Token",
        }
    entry = {
        "credentials": {
            "project": {"credential_type": "project", "token": "<token>"},
            "account": {"credential_type": "account", "secret": "<token>"},
        },
        "operation_credentials": {"manage": "account"},
    }
    if named_only:
        entry["operation_credentials"]["send"] = "project"
    if mutation == "wrong_credential":
        entry["operation_credentials"]["manage"] = "project"
    monkeypatch.setitem(NODE_REGISTRY, "test-credentials", Node)
    monkeypatch.setitem(harness.PROVIDERS, "credentials", (
        "test-credentials", None if named_only else entry["credentials"]["project"],
    ))
    monkeypatch.setattr(harness, "spec_entry", lambda _: (None, entry))
    monkeypatch.setattr(harness, "load_specs", lambda _: [doc])
    report = await harness.run_provider("credentials")
    send, manage = report["operations"]
    if mutation == "wrong_credential":
        assert manage["requests"] == []
        assert "Wrong credential family" in manage["fixture_errors"][0]
    else:
        assert send["passed"]
        assert attempts == [
            ("send", "project", None), ("manage", "account", None),
            ("send", "project", "1"), ("manage", "account", "1"),
        ]
        assert report["fixture_errors"] == 0
        if mutation == "wrong_header":
            assert not manage["passed"]
            assert any("Authentication" in failure for failure in manage["failures"])
        else:
            assert report["passed"] == 2

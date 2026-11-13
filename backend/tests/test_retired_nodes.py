"""A retired integration (its service shut down) is offered by no listing, while a
workflow that already has one keeps loading, validating, running and finding its
credential until the vendor's API refuses it."""
import functools
import json
import re
from pathlib import Path

import httpx
import pytest

from coder.workflow.agentic.node_types import _get_available_node_types
from coder.workflow.operation_catalog import known_credential_types
from coder.workflow.workflow_ops import retired_node_refusal
from nodes import humanloop_node
from nodes.core.base import Retirement
from nodes.core.credential_connect import resolve_credential_class
from nodes.core.discovery import declare_nodes
from nodes.core.registry import NODE_REGISTRY, NodeFactory, is_listed, retirement_of
from tests.judged_nodes import judged_classes, narrowed
from utils import credential_operations

pytestmark = pytest.mark.every_integration


# Read at the first test that needs it, not at import: collecting this file imported every integration on each
# of a shard's workers.
@functools.cache
def _retired():
    return sorted(t for t, cls in judged_classes() if cls.retired)


SCHEMAS = Path(__file__).resolve().parents[2] / "frontend" / "app" / "schemas"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def test_the_dead_services_are_retired_and_the_live_ones_listed():
    assert all(retirement_of(t) for t in ("automation-humanloop", "automation-starton", "automation-rkvst"))
    # Freshteam is sunsetting (renewals stopped 2026-06-07) and ToneDen still answers.
    assert is_listed("automation-freshteam") and is_listed("automation-toneden")
    assert retirement_of("automation-humanloop").since == "2025-09-08"
    assert is_listed("not-a-node") and is_listed(None)


def test_a_retirement_names_its_reason_and_an_iso_date():
    with pytest.raises(ValueError):
        Retirement(reason=" ", since="2025-09-08")
    with pytest.raises(ValueError):
        Retirement(reason="Gone", since="September 2025")


def test_the_generated_schema_publishes_each_retirement():
    discovered = declare_nodes(Path(humanloop_node.__file__).resolve().parent)
    slim = json.loads((SCHEMAS / "nodeMeta.json").read_text())["types"]
    for node_type, cls in judged_classes():
        slug = node_type.removeprefix("automation-")
        path = SCHEMAS / "nodes" / f"{slug}.json"
        if not path.exists():  # no config model, so no schema (trigger-run, test-dummy)
            assert not cls.retired, node_type
            continue
        schema = json.loads(path.read_text())
        meta = (json.loads((SCHEMAS / "nodeMeta" / f"{slug}.json").read_text())["nodeMeta"]
                if node_type in discovered else slim.get(node_type, {}))
        expected = cls.retired.as_json() if cls.retired else None
        assert schema.get("x-retired") == expected, node_type
        assert meta.get("retired") == expected, node_type


def test_no_backend_listing_offers_a_retired_type():
    if narrowed() and not _retired():
        pytest.skip("no judged type is retired")  # the listings import every integration to say nothing of these
    builder_types = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)+", _get_available_node_types()))
    assert "automation-serverless-function" in builder_types  # integrations are named only where demand is known
    assert not builder_types & set(_retired())

    connectable = {op["node_type"] for op in credential_operations._connectable_operations()}
    assert "automation-slack" in connectable
    assert not connectable & set(_retired())


def test_a_new_node_of_a_retired_type_is_refused_with_its_reason():
    refusal = retired_node_refusal("automation-humanloop")
    assert retirement_of("automation-humanloop").reason in refusal
    assert "keep running" in refusal
    assert retired_node_refusal("automation-slack") is None


# --- A workflow that already has one keeps working ---

SAVED = {"config": {"operation": "list_prompts", "page": 1},
         "credentials": {"credential_type": "humanloop_api_key", "api_key": "synthetic-humanloop-key"}}


@pytest.mark.asyncio
async def test_a_saved_retired_node_still_validates_and_runs(monkeypatch):
    assert NODE_REGISTRY["automation-humanloop"].validate_config({"config": SAVED["config"]})["valid"]
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"records": [{"id": "pr_1", "name": "Support"}], "page": 1, "size": 10, "total": 1})

    monkeypatch.setattr(humanloop_node, "guarded_async_client",
                        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs))
    node = NodeFactory.create_node(node_id="saved-humanloop", node_type="automation-humanloop", node_data=SAVED)
    result = await node.execute({})
    assert result["data"] == [{"id": "pr_1", "name": "Support"}]
    assert [r.url.path for r in requests] == ["/v5/prompts"]


def test_an_existing_credential_still_finds_its_retired_service():
    for node_type in _retired():
        for credential_type in credential_operations.connection_catalog()[1].get(node_type, ()):
            assert credential_type in known_credential_types()
            assert node_type in credential_operations.compatible_providers(credential_type)
            assert credential_operations.operation_catalog(credential_type, node_type)
            assert resolve_credential_class(credential_type) is not None
    assert credential_operations.compatible_providers("humanloop_api_key") == ["automation-humanloop"]

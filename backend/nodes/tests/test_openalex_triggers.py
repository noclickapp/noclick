"""OpenAlex polling regressions for the published Work response fields.

Initial work fields copy the provider docs examples cited below. Subsequent IDs
and timestamps simulate changes; these tests make no live-account claim.
"""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from nodes.core.poll_trigger import poll_scope
from nodes.tests.test_openalex_node_mock import node, transport
from nodes.openalex_node import OpenAlexNode

# Field-example projection from the provider's Work object documentation:
# https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/work-object/README.md
# This combines its published field examples; it is not a recorded API response.
WORK = {
    "id": "https://openalex.org/W2741809807",
    "doi": "https://doi.org/10.7717/peerj.4375",
    "display_name": "The state of OA: a large-scale analysis of the prevalence and impact of Open Access articles",
    "updated_date": "2022-01-02T00:22:35.180390",
    "authorships": [{
        "author_position": "middle",
        "author": {"id": "https://openalex.org/A5023888391", "display_name": "Jason Priem",
                   "orcid": "https://orcid.org/0000-0001-6187-6610"},
        "institutions": [{"id": "https://openalex.org/I4200000001", "display_name": "OurResearch",
                          "ror": "https://ror.org/02nr0ka47", "country_code": "US", "type": "nonprofit"}],
    }],
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,sort", [("on_new_work", "created_date:desc"), ("on_new_or_updated_work", "updated_date:desc")])
async def test_baseline_dedup_changes_scope_and_agent_event(monkeypatch, operation, sort):
    n = node({"operation": operation, "search": "bioplastics", "filter": "type:article"})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(state)
        if replacement is not None:
            state = replacement
        return result
    n._update_node_state = update
    n.emit = AsyncMock()
    body = {"results": [deepcopy(WORK)]}
    requests = transport(monkeypatch, body)
    assert (await n.execute({}))["new_work_count"] == 0
    assert (await n.execute({}))["new_work_count"] == 0
    body["results"][0]["updated_date"] = "2026-11-02T00:00:00"
    assert (await n.execute({}))["new_work_count"] == (operation == "on_new_or_updated_work")
    body["results"][0]["id"] = "https://openalex.org/W1"
    fresh = await n.execute({})
    assert fresh["new_work_count"] == 1
    assert (await n.execute({}))["new_work_count"] == 0
    event = OpenAlexNode.resolve_agent_event(fresh)
    assert "W1" in event["text"] and WORK["display_name"] in event["text"] and WORK["doi"] in event["text"]
    assert "Jason Priem" in event["text"]
    assert not OpenAlexNode.should_propagate_output({"new_work_count": 0}, {"operation": operation})
    assert OpenAlexNode.should_propagate_output(fresh, {"operation": operation})
    assert OpenAlexNode.resolve_agent_event({"works": []}) is None
    assert dict(requests[0].url.params) == {"search": "bioplastics", "filter": "type:article", "sort": sort, "per_page": "100", "api_key": "synthetic-openalex-key-42"}
    assert all("schedule" not in request.url.params for request in requests)
    n.config.config.filter = "type:preprint"
    assert (await n.execute({}))["new_work_count"] == 0


def test_poll_scope_ignores_canvas_metadata():
    config = {"operation": "on_new_work", "search": "bioplastics"}
    assert poll_scope(OpenAlexNode, config) == poll_scope(OpenAlexNode, config | {"label": "Renamed"})
    assert poll_scope(OpenAlexNode, config) != poll_scope(OpenAlexNode, config | {"search": "biology"})


@pytest.mark.asyncio
async def test_errors_do_not_advance_poll_state(monkeypatch):
    n = node({"operation": "on_new_or_updated_work"})
    n._update_node_state = AsyncMock()
    transport(monkeypatch, {"error": "Member+ required"}, 403)
    with pytest.raises(ValueError, match="Member"):
        await n.execute({})
    transport(monkeypatch, {"results": [{"id": WORK["id"]}]})
    with pytest.raises(ValueError, match="timestamp"):
        await n.execute({})
    n._update_node_state.assert_not_awaited()

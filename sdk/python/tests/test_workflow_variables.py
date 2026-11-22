"""``Workflow.variables``: a workflow's variables with their values, which no other read carries, against the mocked
transport: what the call sends, how it reads the answer, that a refusal is the API's, and that the values never show
in the object's repr."""

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID

VARIABLES = {
    "object": "workflow_variables", "workflow_id": "wf_1", "version": 12,
    "definitions": [
        {"name": "api_token", "value": "tok-held-back", "description": "The shop's API token"},
        {"name": "repo", "value": "acme/shop", "per_user": True},
        {"name": "region"},
        {"name": "page", "value": "1"},
    ],
    "variables": {"page": 3, "last_cursor": "c_9"},
}


def test_the_owner_reads_each_variable_with_its_value(api, client):
    route = api.get("/v1/workflows/wf_1/variables").respond(json=VARIABLES)
    read = nc.Workflow.from_id("wf_1").variables()
    assert route.called and isinstance(read, nc.WorkflowVariables)
    assert (read.workflow_id, read.version) == ("wf_1", 12)
    assert read.definitions == VARIABLES["definitions"]
    assert read.variables == {"page": 3, "last_cursor": "c_9"}
    # What {{vars.name}} reads: a definition's value, the graph's own over it; one with no value isn't there.
    assert read.values == {"api_token": "tok-held-back", "repo": "acme/shop", "page": 3, "last_cursor": "c_9"}
    assert "NoClick-User" not in route.calls.last.request.headers


def test_its_repr_names_the_variables_and_never_a_value(api, client):
    api.get("/v1/workflows/wf_1/variables").respond(json=VARIABLES)
    shown = repr(nc.Workflow.from_id("wf_1").variables())
    assert "api_token" in shown and "last_cursor" in shown
    assert not any(value in shown for value in ("tok-held-back", "acme/shop", "c_9"))


def test_anyone_but_its_owner_is_refused_as_the_api_refuses_them(api, client):
    api.get("/v1/workflows/wf_1/variables").mock(return_value=httpx.Response(403, json={"error": {
        "type": "permission_denied", "scope": "workflows:variables",
        "message": "This key lacks the 'workflows:variables' scope, which a key with every scope (*) holds only "
                   "when it's named too.",
        "next_step": "Create a key that names the 'workflows:variables' scope."}}))
    with pytest.raises(nc.PermissionDenied) as refused:
        nc.Workflow.from_id("wf_1").variables()
    assert "workflows:variables" in str(refused.value)
    with nc.as_user(USER_ID), pytest.raises(nc.PermissionDenied):
        nc.Workflow.from_id("wf_1").variables()


def test_a_workflow_with_none_reads_empty(api, client):
    api.get("/v1/workflows/wf_1/variables").respond(json={
        "object": "workflow_variables", "workflow_id": "wf_1", "version": 1, "definitions": [], "variables": {}})
    read = nc.Workflow.from_id("wf_1").variables()
    assert (read.definitions, read.variables, read.values) == ([], {}, {})

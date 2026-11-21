"""A workflow's graph through its handles, against the mocked transport answering as the API's
``/v1`` graph routes do: the graph read whole into typed steps, each
single edit as a one-op batch with no version check, a batch sent once and atomically with its
``if_version``, a stale batch refused with the workflow as it stands, an op that can't apply named,
versions paged, read and restored."""

import asyncio

import httpx
import pytest

import noclick as nc
from platform_helpers import body, listing

WF = "wf_1"
EDITS = f"/v1/workflows/{WF}/edits"
CREDENTIAL = "9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e"

HOOK = {"id": "hook", "type": "trigger-webhook", "position": {"x": 0, "y": 0},
        "config": {"label": "New order", "http_method": "POST", "webhook_url": "https://wf-1.noclick.run"}}
WRITER = {"id": "writer", "type": "agent", "position": {"x": 320, "y": 0},
          "config": {"label": "Writer", "operation": "default", "model": "openrouter/anthropic/claude-sonnet-4",
                     "system_prompt": "Summarize the order.", "credentialIds": {"agent_openrouter": CREDENTIAL},
                     "channel__label": "#orders"}}
LINEAR = {"id": "linear", "type": "automation-linear", "position": {"x": 320, "y": 200},
          "config": {"label": "Linear", "operation": "create_issue", "disabled": True,
                     "mockedOutput": {"id": "ISS-1"}}}
# A step the canvas saved in its own shape: its fields beside data.config.
CANVAS = {"id": "post", "type": "automation-slack", "position": {"x": 640, "y": 0},
          "data": {"label": "Post it", "operation": "send_message_to_channel", "disabled": False,
                   "config": {"channel": "#team", "text": "{{ $('writer').text }}"}}}
NOTE = {"id": "stickyNote-1-abc123", "type": "stickyNote", "position": {"x": 0, "y": -150},
        "config": {"content": "Orders land here.", "color": 8}, "width": 240, "height": 120}
EDGES = [{"id": "hook-writer", "source": "hook", "target": "writer", "type": "animated"},
         {"id": "linear-writer", "source": "linear", "target": "writer", "type": "animated",
          "targetHandle": "bottom"},
         {"id": "writer-post", "source": "writer", "target": "post", "type": "animated"}]


def bare(*nodes, edges=EDGES, withheld=None):
    """A graph as the routes show one (``public_graph``): nodes as stored, edges, the secrets left out."""
    return {"nodes": list(nodes or (HOOK, WRITER, LINEAR, CANVAS, NOTE)), "edges": list(edges),
            "withheld": withheld if withheld is not None else {"writer": ["api_key"]}}


DEFINITION = {"name": "Order intake", "description": "Files each order.",
              "settings": {"variable_definitions": [{"name": "team", "value": "#orders"}, {"name": "token"}]},
              "settings_withheld": ["variable_definitions[1].value"]}


def read(version=4, graph=None):
    """``GET /v1/workflows/{id}/graph``: the workflow's definition, its secrets left out by path."""
    return {"object": "workflow_graph", "workflow_id": WF, "version": version, **DEFINITION, "graph": graph or bare()}


def edited(version, results, *, steps=None, graph=None, changed=True, history_version=None, summary="changed it"):
    """``POST /v1/workflows/{id}/edits``; with ``include_graph``, the definition as ``/graph`` reads it."""
    answer = {"object": "workflow_edit", "workflow_id": WF, "version": version, "changed": changed,
              "history_version": history_version if history_version is not None or not changed else version,
              "summary": summary, "results": results, "steps": steps or {}}
    if graph is not None:
        answer.update(DEFINITION, graph=graph)
    return answer


def stale(version, graph):
    """The 409 a stale ``if_version`` answers: the workflow as it stands."""
    return httpx.Response(409, json={"error": {
        "type": "conflict", "message": f"The workflow is at version {version}, not 4: it changed since it was read.",
        "next_step": "Apply the edits to the graph returned here and send them again with if_version set to its "
                     "version.", "workflow_id": WF, "version": version, "graph": graph}})


def version_row(history_version, version=None, source="api", **extra):
    """A version of the history: its own number, fixed, and the workflow's version its latest write left."""
    author = None if source == "baseline" else {"user_id": "u_1", "key_id": "key_1"}
    return {"object": "workflow_version", "workflow_id": WF, "history_version": history_version,
            "version": version if version is not None else history_version + 10, "source": source,
            "author": author, "authors": [author] if author else [],
            "summary": f"version {history_version}", "changes": [f"version {history_version}"], "restored_from": None,
            "created_at": "2026-10-30T10:00:00Z", "updated_at": "2026-10-30T10:04:00Z", **extra}


def view(version=4, **extra):
    """``GET /v1/workflows/{id}``: the workflow at a glance, with its version."""
    return {"object": "workflow", "id": WF, "name": "Order intake", "description": "Files each order.",
            "version": version, "access": "owner", "steps": [], **extra}


# --- reading -------------------------------------------------------------------------

def test_a_graph_reads_the_whole_definition_into_typed_steps_notes_and_edges(api, client):
    route = api.get(f"/v1/workflows/{WF}/graph").respond(json=read(graph=bare(
        HOOK, WRITER, LINEAR, CANVAS, NOTE, withheld={"writer": ["api_key"], "hook": ["headers[0].value"]})
        | {"variables_withheld": ["api_base"]}))
    workflow = nc.Workflow.from_id(WF)
    graph = workflow.graph()
    assert route.call_count == 1 and "NoClick-User" not in route.calls.last.request.headers
    assert isinstance(graph, nc.WorkflowGraph) and (graph.workflow_id, graph.version, workflow.version) == (WF, 4, 4)
    assert (graph.name, graph.description, graph.settings, graph.settings_withheld) == (
        "Order intake", "Files each order.", DEFINITION["settings"], ["variable_definitions[1].value"])
    assert graph.variables_withheld == ["api_base"]
    assert graph.withheld == {"writer": ["api_key"], "hook": ["headers[0].value"]}

    assert [s.id for s in graph.steps] == ["hook", "writer", "linear", "post"]
    hook, writer, linear, post = graph.steps
    assert (hook.type, hook.name, hook.operation, hook.enabled) == ("trigger-webhook", "New order", None, True)
    assert hook.settings == {"http_method": "POST", "webhook_url": "https://wf-1.noclick.run"}
    assert hook.withheld == ["headers[0].value"]
    # Its name, operation and connections are fields of their own, never settings; the app's label cache isn't one.
    assert writer.settings == {"model": "openrouter/anthropic/claude-sonnet-4", "system_prompt": "Summarize the order."}
    assert (writer.connections, writer.withheld, writer.position) == (
        {"agent_openrouter": CREDENTIAL}, ["api_key"], {"x": 320, "y": 0})
    assert (linear.enabled, linear.mock_output, linear.settings) == (False, {"id": "ISS-1"}, {})
    assert (post.name, post.operation, post.settings) == (
        "Post it", "send_message_to_channel", {"channel": "#team", "text": "{{ $('writer').text }}"})
    assert writer.verdict is None and writer.notes == {} and writer.workflow is workflow

    [note] = graph.notes
    assert (note.type, note.settings["content"]) == ("stickyNote", "Orders land here.")
    assert graph.edges == [
        {"id": "hook-writer", "from": "hook", "to": "writer", "kind": "data", "handle": None},
        {"id": "linear-writer", "from": "linear", "to": "writer", "kind": "tools", "handle": None},
        {"id": "writer-post", "from": "writer", "to": "post", "kind": "data", "handle": None},
    ]
    assert graph.step("writer") is writer and graph.step("Post it") is post
    with pytest.raises(nc.NotFound):
        graph.step("Nope")


def test_the_workflows_version_comes_with_its_read_and_moves_with_each_answer(api, client):
    api.get(f"/v1/workflows/{WF}").respond(json=view(7))
    api.post(f"/v1/workflows/{WF}/pause").respond(json=view(8, paused=True))
    api.post(EDITS).respond(json=edited(9, [{"op": "layout"}], changed=False))
    workflow = nc.Workflow.from_id(WF)
    assert workflow.version == 7  # read with the workflow
    workflow.pause("Quiet week")
    assert workflow.version == 8  # a pause writes its triggers' records
    with workflow.edit(if_version=workflow.version) as e:
        e.layout()
    assert workflow.version == 9 and e.result.history_version is None  # moving things is no version of the history
    listed = nc.Workflow._new(raw=view(3), user=None)
    assert listed.version == 3


def test_a_name_two_steps_share_is_refused_by_name(api, client):
    twin = {**CANVAS, "id": "post2"}
    api.get(f"/v1/workflows/{WF}/graph").respond(json=read(graph=bare(CANVAS, twin, edges=[])))
    graph = nc.Workflow.from_id(WF).graph()
    with pytest.raises(nc.Conflict) as shared:
        graph.step("Post it")
    assert shared.value.ids == ["post", "post2"]
    assert graph.step("post2").id == "post2"


def test_a_step_handle_sends_nothing_until_a_field_is_read(api, client):
    route = api.get(f"/v1/workflows/{WF}/graph").respond(json=read())
    workflow = nc.Workflow.from_id(WF)
    writer = workflow.step("writer")
    assert route.call_count == 0 and writer.id == "writer" and not writer.is_hydrated
    assert writer.name == "Writer" and route.call_count == 1
    # Another handle reads from the graph this one loaded; refresh reads it again.
    assert workflow.step("hook").type == "trigger-webhook" and route.call_count == 1
    writer.refresh()
    assert route.call_count == 2
    with pytest.raises(nc.NotFound) as missing:
        _ = workflow.step("ghost").settings
    assert missing.value.step == "ghost"


# --- single edits ----------------------------------------------------------------------

def test_add_step_is_one_edit_with_its_id_and_the_graph_as_written(api, client):
    added = {"id": "done", "type": "log", "position": {"x": 640, "y": 200},
             "config": {"label": "Done", "message": "ok"}}
    route = api.post(EDITS).respond(json=edited(
        5, [{"op": "add_step", "id": "done", "resolutions": {"message": "ok"}}],
        steps={"done": {"config_valid": True}}, graph=bare(HOOK, added, edges=[])))
    workflow = nc.Workflow.from_id(WF)
    done = workflow.add_step("log", name="Done", settings={"message": "ok"}, id="done")
    assert body(route.calls.last.request) == {
        "ops": [{"op": "add_step", "type": "log", "settings": {"message": "ok"}, "name": "Done", "id": "done"}],
        "include_graph": True}
    assert isinstance(done, nc.Step) and (done.id, done.name, done.position) == ("done", "Done", {"x": 640, "y": 200})
    assert done.verdict == {"config_valid": True} and done.notes == {"resolutions": {"message": "ok"}}
    assert workflow.version == 5 and workflow.last_edit.results[0]["id"] == "done"

    # Left without an id, it's named from its type, as the API names one, so the answer's graph finds it.
    workflow.add_step("automation-gmail", operation="send_email_message", position=(10, 20))
    op = body(route.calls.last.request)["ops"][0]
    assert op["id"].startswith("automation-gmail-") and op["position"] == {"x": 10, "y": 20}
    assert "if_version" not in body(route.calls.last.request)


def test_each_step_method_is_one_op(api, client):
    graph = bare()
    route = api.post(EDITS).respond(json=edited(5, [{"op": "x", "id": "writer"}], graph=graph))
    workflow = nc.Workflow.from_id(WF)
    writer = workflow.step("writer")

    def sent():
        return body(route.calls.last.request)["ops"]

    assert writer.update(settings={"system_prompt": "Be brief."}, name="Brief writer", enabled=False) is writer
    assert sent() == [{"op": "update_step", "id": "writer", "settings": {"system_prompt": "Be brief."},
                       "name": "Brief writer", "enabled": False}]
    writer.update(operation="default")
    assert sent() == [{"op": "update_step", "id": "writer", "operation": "default"}]
    writer.patch("system_prompt", "@@ Summarize\n-Summarize the order.\n+Summarize it.")
    assert sent() == [{"op": "patch_step", "id": "writer", "field": "system_prompt",
                       "patch": "@@ Summarize\n-Summarize the order.\n+Summarize it."}]
    workflow.step("hook").connect(writer)
    assert sent() == [{"op": "connect", "from": "hook", "to": "writer", "kind": "data"}]
    workflow.step("linear").connect("writer", kind="tools")
    assert sent() == [{"op": "connect", "from": "linear", "to": "writer", "kind": "tools"}]
    workflow.step("loop").connect("writer", handle="loop")
    assert sent() == [{"op": "connect", "from": "loop", "to": "writer", "kind": "data", "handle": "loop"}]
    workflow.step("hook").disconnect("writer")
    assert sent() == [{"op": "disconnect", "from": "hook", "to": "writer"}]
    writer.mock({"text": "A summary."})
    assert sent() == [{"op": "mock_step", "id": "writer", "output": {"text": "A summary."}}]
    writer.unmock()
    assert sent() == [{"op": "unmock_step", "id": "writer"}]
    assert writer.remove() is None
    assert sent() == [{"op": "remove_step", "id": "writer"}]
    # One op each, never a version check, and always the graph back.
    assert all("if_version" not in body(c.request) and body(c.request)["include_graph"] for c in route.calls)


def test_set_connection_sends_a_connections_ref_its_name_or_id_and_none_takes_one_off(api, client):
    route = api.post(EDITS).respond(json=edited(5, [{"op": "set_connection", "id": "post", "slot": "slack_oauth"}],
                                                 graph=bare()))
    post = nc.Workflow.from_id(WF).step("post")
    post.set_connection(nc.Connection.from_id(f"credential:{CREDENTIAL}"))
    assert body(route.calls.last.request)["ops"] == [
        {"op": "set_connection", "id": "post", "connection": f"credential:{CREDENTIAL}"}]
    named = "4c1e9a2b-7f3d-4e8a-9b6c-2d5f8e1a3c7b"
    post.set_connection(nc.Connection.from_id(named))
    assert body(route.calls.last.request)["ops"][0]["connection"] == named
    post.set_connection("work-slack")
    assert body(route.calls.last.request)["ops"][0]["connection"] == "work-slack"
    post.set_connection(CREDENTIAL, slot="slack_oauth")
    assert body(route.calls.last.request)["ops"] == [
        {"op": "set_connection", "id": "post", "connection": CREDENTIAL, "slot": "slack_oauth"}]
    post.set_connection(None, slot="slack_oauth")
    assert body(route.calls.last.request)["ops"] == [
        {"op": "set_connection", "id": "post", "connection": None, "slot": "slack_oauth"}]
    assert post.notes == {"slot": "slack_oauth"}


def test_an_edit_surfaces_its_notes_and_verdicts(api, client):
    switched = {**WRITER, "config": {"label": "Writer", "model": "codex", "codex_model": "gpt-5"}}
    switch = {"from": "sdk", "to": "codex", "removed_fields": ["temperature"], "unlinked_credentials": ["openrouter"]}
    api.post(EDITS).respond(json=edited(
        5, [{"op": "update_step", "id": "writer", "changed": True, "harness_switch": switch,
             "coerced_values": [{"field": "max_turns", "from": "3", "to": 3}]}],
        steps={"writer": {"config_valid": False, "validation_error": "Codex needs an OpenAI key.",
                          "missing_required": ["credentials"], "agent_credential_hint": "Connect an OpenAI key."},
               "post": {"config_valid": True}},
        graph=bare(HOOK, switched, edges=[])))
    workflow = nc.Workflow.from_id(WF)
    writer = workflow.step("writer").update(settings={"model": "codex"})
    assert writer.notes == {"changed": True, "harness_switch": switch,
                            "coerced_values": [{"field": "max_turns", "from": "3", "to": 3}]}
    assert writer.verdict["config_valid"] is False and writer.verdict["missing_required"] == ["credentials"]
    assert writer.settings == {"model": "codex", "codex_model": "gpt-5"} and writer.connections == {}
    assert workflow.last_edit.steps["post"] == {"config_valid": True}
    assert writer.references == [] and workflow.step("post").references == []


def test_an_edit_names_the_reads_that_wont_resolve(api, client):
    unresolved = [{"field": "message", "step": "hook", "key": "ordr_id", "known_keys": ["order_id", "total"]},
                  {"field": "message", "step": "hok", "reference": "{{ $('hok').order_id }}", "missing": True,
                   "near": "hook"}]
    api.post(EDITS).respond(json=edited(
        5, [{"op": "update_step", "id": "linear", "changed": True}],
        steps={"linear": {"config_valid": True, "references": unresolved}}, graph=bare(HOOK, LINEAR, edges=[])))
    workflow = nc.Workflow.from_id(WF)
    linear = workflow.step("linear").update(settings={"title": "{{ $('hook').ordr_id }} {{ $('hok').order_id }}"})
    assert linear.references == unresolved and linear.verdict["references"] == unresolved
    assert workflow.last_edit.steps["linear"]["references"][0]["known_keys"] == ["order_id", "total"]


def test_the_workflows_own_fields_notes_and_moves(api, client):
    route = api.post(EDITS).respond(json=edited(5, [{"op": "x", "id": "stickyNote-9"}], graph=bare()))
    api.get(f"/v1/workflows/{WF}").respond(json={"object": "workflow", "id": WF, "name": "Order desk",
                                                 "description": "Files each order in Linear."})
    workflow = nc.Workflow.from_id(WF)
    assert workflow.update(name="Order desk", description="Files each order in Linear.") is workflow
    assert body(route.calls.last.request)["ops"] == [
        {"op": "update_workflow", "name": "Order desk", "description": "Files each order in Linear."}]
    # The edit may have renamed it: the next read loads the workflow again.
    assert workflow.name == "Order desk"
    workflow.update(settings={"theme": "dark"})
    assert body(route.calls.last.request)["ops"] == [{"op": "update_workflow", "settings": {"theme": "dark"}}]

    note = workflow.add_note("Orders land here.", near=[workflow.step("hook"), "writer"], color=3)
    sent = body(route.calls.last.request)["ops"][0]
    assert sent == {"op": "add_note", "content": "Orders land here.", "id": sent["id"], "color": 3,
                    "near": ["hook", "writer"]}
    assert sent["id"].startswith("stickyNote-") and note.id == sent["id"]
    workflow.add_note("The order stretch.", id="span", after="hook", before="post")
    assert body(route.calls.last.request)["ops"] == [
        {"op": "add_note", "content": "The order stretch.", "id": "span", "after": "hook", "before": "post"}]

    moved = workflow.move("post", {"x": 900, "y": 40})
    assert body(route.calls.last.request)["ops"] == [{"op": "move", "id": "post", "position": {"x": 900, "y": 40}}]
    assert moved.id == "post" and moved.position == {"x": 640, "y": 0}  # the answer's graph says where it is


# --- batches -----------------------------------------------------------------------------

def test_a_batch_is_one_request_in_order_with_its_version_and_later_ops_name_new_steps(api, client):
    added = {"id": "post2", "type": "automation-slack", "position": {"x": 0, "y": 0},
             "config": {"label": "Post again", "operation": "send_message_to_channel"}}
    route = api.post(EDITS).respond(json=edited(
        5, [{"op": "add_step", "id": "post2"}, {"op": "connect", "from": "writer", "to": "post2", "kind": "data",
                                                "edge_id": "writer-post2"},
            {"op": "update_step", "id": "writer", "changed": True}, {"op": "define_variable", "name": "team"},
            {"op": "add_test_run", "name": "Big order", "slug": "big-order", "trigger_type": "trigger-webhook"},
            {"op": "layout"}],
        steps={"post2": {"config_valid": False, "missing_required": ["channel"]}},
        graph=bare(HOOK, WRITER, added), summary="added 'Post again'; connected 'Writer' to 'Post again'"))
    workflow = nc.Workflow.from_id(WF)
    with workflow.edit(if_version=4, include_graph=True) as e:
        again = e.add_step("automation-slack", operation="send_message_to_channel", name="Post again", id="post2")
        e.connect("writer", again)
        e.update_step(workflow.step("writer"), settings={"system_prompt": "Be brief."})
        e.define_variable("team", value="#team", description="Where it posts")
        e.add_test_run("hook", "Big order", '{"total": 900}', title="A big order")
        e.layout()
        assert route.call_count == 0 and len(e.ops) == 6
    assert route.call_count == 1
    assert body(route.calls.last.request) == {"if_version": 4, "include_graph": True, "ops": [
        {"op": "add_step", "type": "automation-slack", "operation": "send_message_to_channel", "name": "Post again",
         "id": "post2"},
        {"op": "connect", "from": "writer", "to": "post2", "kind": "data"},
        {"op": "update_step", "id": "writer", "settings": {"system_prompt": "Be brief."}},
        {"op": "define_variable", "name": "team", "value": "#team", "description": "Where it posts"},
        {"op": "add_test_run", "trigger": "hook", "name": "Big order", "body": '{"total": 900}', "title": "A big order"},
        {"op": "layout"},
    ]}
    result = e.result
    assert isinstance(result, nc.WorkflowEdit)
    assert (result.version, result.history_version, result.changed) == (5, 5, True)
    assert result.summary.startswith("added 'Post again'") and [r["op"] for r in result.results][:2] == [
        "add_step", "connect"]
    # Asked for the graph, the answer is the workflow as written, as graph() reads it.
    assert [s.id for s in result.graph.steps] == ["hook", "writer", "post2"]
    assert (result.graph.name, result.graph.settings_withheld) == ("Order intake", ["variable_definitions[1].value"])
    # The step the batch added knows what the batch said about it, and reads from the graph it wrote.
    assert again.verdict == {"config_valid": False, "missing_required": ["channel"]} and again.name == "Post again"
    assert workflow.version == 5 and workflow.last_edit is result
    with pytest.raises(RuntimeError):
        e.layout()


def test_a_batch_whose_block_raises_or_holds_nothing_sends_nothing(api, client):
    route = api.post(EDITS).respond(json=edited(5, []))
    workflow = nc.Workflow.from_id(WF)
    with pytest.raises(ValueError):
        with workflow.edit() as e:
            e.remove_step("writer")
            raise ValueError("changed my mind")
    with workflow.edit() as empty:
        pass
    assert route.call_count == 0 and e.result is None and empty.result is None


def test_a_batch_from_async_code(api, client):
    route = api.post(EDITS).respond(json=edited(5, [{"op": "remove_step", "id": "writer"}]))

    async def main():
        workflow = nc.Workflow.from_id(WF)
        async with workflow.edit(if_version=4) as e:
            e.remove_step("writer")
            e.set_connection("post", nc.Connection.from_id(f"credential:{CREDENTIAL}"))
        return e.result

    result = asyncio.run(main())
    assert result.version == 5 and body(route.calls.last.request) == {"if_version": 4, "ops": [
        {"op": "remove_step", "id": "writer"},
        {"op": "set_connection", "id": "post", "connection": f"credential:{CREDENTIAL}"}]}


def test_an_agent_steps_secrets_go_by_name_whatever_names_them(api, client):
    """``secrets=`` on an agent step (its update, a batch's add or update, the workflow's add): names, or
    ``noclick.Secret`` objects sent as their names; ``[]`` takes them all off. Never a value."""
    route = api.post(EDITS).respond(json=edited(5, [{"op": "update_step", "id": "writer"}], graph=bare()))
    api.get("/v1/secrets").respond(json=listing({"object": "secret", "id": "sec_1", "name": "shipping",
                                                "keys": ["SHIPPING_TOKEN"], "user_id": None, "used_by": []}))
    workflow = nc.Workflow.from_id(WF)
    workflow.step("writer").update(secrets=["warehouse", nc.Secret.from_name("shipping")])
    assert body(route.calls.last.request)["ops"] == [
        {"op": "update_step", "id": "writer", "settings": {"secrets": ["warehouse", "shipping"]}}]
    workflow.step("writer").update(settings={"message": "Go."}, secrets="warehouse")
    assert body(route.calls.last.request)["ops"][0]["settings"] == {"message": "Go.", "secrets": ["warehouse"]}
    workflow.step("writer").update(secrets=[])
    assert body(route.calls.last.request)["ops"][0]["settings"] == {"secrets": []}

    with workflow.edit() as e:
        e.add_step("agent", id="second", settings={"model": "openrouter/anthropic/claude-sonnet-4"},
                   secrets=[nc.Secret.from_name("shipping")])
        e.update_step("writer", secrets=["warehouse"])
    assert body(route.calls.last.request)["ops"] == [
        {"op": "add_step", "type": "agent", "id": "second",
         "settings": {"model": "openrouter/anthropic/claude-sonnet-4", "secrets": ["shipping"]}},
        {"op": "update_step", "id": "writer", "settings": {"secrets": ["warehouse"]}}]


# --- refusals ----------------------------------------------------------------------------

def test_a_stale_batch_is_a_conflict_carrying_the_workflow_as_it_stands(api, client):
    now = bare(HOOK, {**WRITER, "config": {**WRITER["config"], "label": "Renamed"}}, edges=[])
    route = api.post(EDITS).mock(side_effect=[stale(6, now), httpx.Response(200, json=edited(7, [
        {"op": "update_step", "id": "writer", "changed": True}]))])
    workflow = nc.Workflow.from_id(WF)
    with pytest.raises(nc.Conflict) as changed:
        with workflow.edit(if_version=4) as e:
            e.update_step("writer", name="Writer v2")
    error = changed.value
    assert (error.version, error.workflow_id) == (6, WF) and "if_version" in error.next_step
    assert isinstance(error.graph, nc.WorkflowGraph) and error.graph.version == 6
    assert error.graph.step("writer").name == "Renamed"
    # The handle now knows the workflow as it stands: read, decide again, send again.
    assert workflow.version == 6 and workflow.step("writer").name == "Renamed" and e.result is None
    with workflow.edit(if_version=workflow.version) as again:
        again.update_step("writer", name="Writer v2")
    assert body(route.calls.last.request)["if_version"] == 6 and again.result.version == 7


def test_the_documented_retry_loop_decides_again_from_the_conflicts_graph(api, client):
    first = bare(HOOK, WRITER, CANVAS, edges=[])
    moved_on = bare(HOOK, WRITER, {**CANVAS, "data": {**CANVAS["data"], "config": {
        **CANVAS["data"]["config"], "channel": "#sales"}}}, edges=[])
    api.get(f"/v1/workflows/{WF}/graph").respond(json=read(4, first))
    route = api.post(EDITS).mock(side_effect=[stale(5, moved_on), httpx.Response(200, json=edited(6, []))])
    workflow = nc.Workflow.from_id(WF)
    graph = workflow.graph()
    for _ in range(3):
        post = graph.step("Post it")
        try:
            with workflow.edit(if_version=graph.version) as e:
                e.update_step(post, settings={"text": f"{post.settings['channel']}: done"})
            break
        except nc.Conflict as changed:
            graph = changed.graph
    assert [body(c.request)["if_version"] for c in route.calls] == [4, 5]
    assert body(route.calls.last.request)["ops"][0]["settings"] == {"text": "#sales: done"}


def test_an_op_that_cant_apply_is_named_and_nothing_lands(api, client):
    api.post(EDITS).respond(400, json={"error": {
        "type": "invalid_request", "message": "No step 'ghost' in this workflow.",
        "next_step": "Fix ops[1] and send the batch again; nothing of it was applied.", "field": "ops[1].id",
        "op": 1}})
    workflow = nc.Workflow.from_id(WF)
    with pytest.raises(nc.InvalidRequest) as refused:
        with workflow.edit() as e:
            e.update_step("writer", name="Kept?")
            e.remove_step("ghost")
    assert (refused.value.field, refused.value.op) == ("ops[1].id", 1) and e.result is None
    assert workflow._version is None and workflow.last_edit is None


def test_an_agents_workflow_is_refused_as_its_agents(api, client):
    """It changes through the agent: the refusal names it, and nothing about the handle moves."""
    api.post(EDITS).respond(403, json={"error": {
        "type": "permission_denied", "message": "'helper' is the workflow the agent 'helper' runs on.",
        "next_step": "Change or message the agent (/v1/agents/ag_1).", "agent_id": "ag_1"}})
    workflow = nc.Workflow.from_id(WF)
    with pytest.raises(nc.PermissionDenied) as refused:
        workflow.step("agent").update(settings={"system_prompt": "Help."})
    assert refused.value.agent_id == "ag_1" and workflow.last_edit is None


def test_a_batch_held_for_the_owner_surfaces_as_its_approval_and_lands_nothing(api, client):
    """A removal of a step holding an app, from an agent or a connected app, waits for the account's owner."""
    api.get(f"/v1/workflows/{WF}/graph").respond(json=read())
    api.post(EDITS).respond(402, json={"error": {
        "type": "approval_required", "message": "Edit 'Order intake': it waits for the account's owner.",
        "next_step": "Tell them to tap the link NoClick sent them.", "status": "awaiting_approval",
        "approval_id": "appr_1", "operation_id": "op_held", "summary": "Edit 'Order intake'",
        "sent_to": ["whatsapp"], "expires_at": "2026-10-31T10:00:00Z"}})
    workflow = nc.Workflow.from_id(WF)
    workflow.graph()
    with pytest.raises(nc.ApprovalRequired) as held:
        with workflow.edit(if_version=4) as e:
            e.remove_step("post")
    assert (held.value.approval_id, held.value.operation_id, held.value.sent_to) == ("appr_1", "op_held", ["whatsapp"])
    assert held.value.details["status"] == "awaiting_approval"
    # The held batch is its own operation: NoClick applies it once the owner approves.
    assert (held.value.operation.id, held.value.operation.kind) == ("op_held", "gate.held_call")
    # Nothing landed: the handle still holds the version and graph it read.
    assert (workflow.version, workflow.last_edit, e.result) == (4, None, None)
    assert workflow.step("post").name == "Post it"


def test_a_conflicts_graph_holds_the_steps_alone(api, client):
    api.post(EDITS).respond(409, json=stale(6, bare(HOOK, edges=[])).json())
    with pytest.raises(nc.Conflict) as changed:
        with nc.Workflow.from_id(WF).edit(if_version=4) as e:
            e.layout()
    graph = changed.value.graph
    assert [s.id for s in graph.steps] == ["hook"]
    assert (graph.name, graph.description, graph.settings, graph.settings_withheld) == (None, None, None, None)


def test_a_conflict_elsewhere_has_no_graph():
    error = nc.Conflict("It already exists.", details={"existing_id": "ag_1"})
    assert (error.graph, error.version, error.existing_id) == (None, None, "ag_1")


# --- versions ----------------------------------------------------------------------------

def test_versions_page_through_the_cursor(api, client):
    route = api.get(f"/v1/workflows/{WF}/versions").mock(side_effect=[
        httpx.Response(200, json=listing(version_row(5, 15), version_row(4, 12, "canvas", authors=[
            {"user_id": "u_1", "key_id": "key_1"}, {"user_id": "u_2", "key_id": None}]), next_cursor="12")),
        httpx.Response(200, json=listing(version_row(3, 9, "restore", restored_from=1),
                                         version_row(1, 1, "baseline")))])
    workflow = nc.Workflow.from_id(WF)
    versions = workflow.versions(limit=None)
    assert [(v.history_version, v.version, v.source) for v in versions] == [
        (5, 15, "api"), (4, 12, "canvas"), (3, 9, "restore"), (1, 1, "baseline")]
    assert route.calls[1].request.url.params["cursor"] == "12"
    assert versions[0].author == {"user_id": "u_1", "key_id": "key_1"} and versions[3].author is None
    # A canvas session is one version, whoever edited in it: its author first.
    assert versions[1].authors == [{"user_id": "u_1", "key_id": "key_1"}, {"user_id": "u_2", "key_id": None}]
    assert versions[0].authors == [versions[0].author] and versions[3].authors == []
    assert versions[2].restored_from == 1 and versions[0].graph is None
    assert versions[0].created_at.year == 2026 and versions[0].changes == ["version 5"]


def test_one_page_of_versions_and_one_version_with_its_whole_definition(api, client):
    page_route = api.get(f"/v1/workflows/{WF}/versions").respond(
        json=listing(version_row(5), next_cursor="15"))
    detail = version_row(2, graph=bare(HOOK, WRITER, edges=[]))
    api.get(f"/v1/workflows/{WF}/versions/2").respond(json={**detail, **DEFINITION, "name": "Order intake (old)"})
    api.get(f"/v1/workflows/{WF}/versions/9").respond(404, json={"error": {
        "type": "not_found", "message": "This workflow has no version 9."}})
    workflow = nc.Workflow.from_id(WF)
    page = workflow.versions_page(limit=1, cursor="20")
    assert [v.history_version for v in page.data] == [5] and page.next_cursor == "15"
    assert page_route.calls.last.request.url.params["limit"] == "1"
    two = workflow.version_at(2)
    assert isinstance(two, nc.WorkflowVersion) and (two.history_version, two.version) == (2, 12)
    assert [s.id for s in two.graph.steps] == ["hook", "writer"] and two.graph.version == 12
    assert (two.graph.name, two.graph.description, two.graph.settings_withheld) == (
        "Order intake (old)", "Files each order.", ["variable_definitions[1].value"])
    with pytest.raises(nc.NotFound):
        workflow.version_at(9)


def test_restoring_a_version_is_a_version_of_its_own_and_checks_the_version_it_is_given(api, client):
    route = api.post(f"/v1/workflows/{WF}/versions/2/restore").mock(side_effect=[
        stale(6, bare(HOOK, edges=[])),
        httpx.Response(200, json={**edited(7, [], summary="restored version 2", history_version=4),
                                  "restored_from": 2})])
    workflow = nc.Workflow.from_id(WF)
    with pytest.raises(nc.Conflict) as changed:
        workflow.restore(history_version=2, if_version=5)
    assert body(route.calls.last.request) == {"if_version": 5}
    assert (changed.value.version, workflow.version) == (6, 6)
    assert workflow.restore(history_version=2) is workflow
    assert body(route.calls.last.request) == {}
    edit = workflow.last_edit
    assert (workflow.version, edit.history_version, edit.restored_from, edit.summary) == (
        7, 4, 2, "restored version 2")
    with pytest.raises(TypeError):
        workflow.restore(if_version=7)


def test_restore_without_a_version_still_brings_it_back_from_the_trash(api, client):
    route = api.post(f"/v1/workflows/{WF}/restore").respond(json=view(3, name="x"))
    workflow = nc.Workflow.from_id(WF)
    assert workflow.restore().name == "x" and route.called and workflow.version == 3


# --- from_name ---------------------------------------------------------------------------

def test_from_name_with_a_description_gets_then_sets_it_where_it_differs(api, client):
    row = {"object": "workflow", "id": WF, "name": "Order intake", "description": "Old."}
    api.get("/v1/workflows").respond(json=listing(row))
    edits = api.post(EDITS).respond(json=edited(4, [{"op": "update_workflow"}], changed=False))
    api.get(f"/v1/workflows/{WF}").respond(json={**row, "description": "Files each order."})
    workflow = nc.Workflow.from_name("Order intake", description="Files each order.")
    assert workflow.description == "Files each order."
    assert body(edits.calls.last.request) == {"ops": [{"op": "update_workflow", "description": "Files each order."}]}
    # As it already has it, nothing is set; and the bare handle only looks it up.
    nc.Workflow.from_name("Order intake", description="Old.").hydrate()
    nc.Workflow.from_name("Order intake").hydrate()
    assert edits.call_count == 1


def test_a_step_by_name_through_from_name_loads_the_workflow_once(api, client):
    lookup = api.get("/v1/workflows").respond(json=listing({"object": "workflow", "id": WF, "name": "Order intake"}))
    route = api.post(EDITS).respond(json=edited(5, [{"op": "connect"}], graph=bare()))
    workflow = nc.Workflow.from_name("Order intake")
    workflow.step("hook").connect("writer")
    workflow.step("writer").connect("post")
    assert lookup.call_count == 1 and route.call_count == 2
    assert lookup.calls.last.request.url.params["name"] == "Order intake"

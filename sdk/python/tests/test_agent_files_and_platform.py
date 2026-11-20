"""NoClick itself as an agent's tools (``noclick.Platform``), files sent with a message, and the typed events a
turn shows (``file``, ``approval``, ``operation``) in a stream, a watch and the history alike."""

import httpx
import pytest

import noclick as nc
from platform_helpers import agent_row, body, operation

AGENT = agent_row(id="ag_1", name="ops")
REPORT = {"object": "agent_attachment", "id": "att_1", "agent_id": "ag_1", "name": "q3.pdf",
          "mime_type": "application/pdf", "size_bytes": 1200, "kind": "file", "voice": False,
          "url": "https://assets.example/u/account/att_1/q3.pdf", "duration_ms": None, "peaks": None}
CLIP = {**REPORT, "id": "att_2", "name": "question.mp3", "mime_type": "audio/mpeg", "kind": "audio", "voice": True,
        "url": "https://assets.example/u/account/att_2/question.mp3", "duration_ms": 3100, "peaks": None}
SHOWN = {"name": "q3.pdf", "url": REPORT["url"], "mime_type": "application/pdf", "size_bytes": 1200}
SSE = (
    'event: file\ndata: {"role": "user", "file": %s, "operation_id": "op_1"}\n\n'
    'event: tool_call\ndata: {"tool": "noclick__buy", "arguments": {"quote_id": "qt_1"}, "operation_id": "op_1"}\n\n'
    'event: approval\ndata: {"approval": {"id": "ap_1", "url": "https://noclick.com/approve/ap_1", '
    '"summary": "Buy +1 415 555 0100", "price": {"amount_usd": 1.15}, "expires_at": "2026-10-16T10:00:00Z"}, '
    '"operation_id": "op_1"}\n\n'
    'event: operation\ndata: {"operation": {"id": "op_2", "status": "running", "summary": "Deploy acme-site"}, '
    '"operation_id": "op_1"}\n\n'
    'event: file\ndata: {"role": "assistant", "file": {"name": "plan.md", "url": "https://assets.example/plan.md", '
    '"mime_type": "text/markdown"}, "operation_id": "op_1"}\n\n'
    'event: done\ndata: {"text": "Waiting for your approval.", "conversation": "desk", "operation_id": "op_1"}\n\n'
) % ('{"name": "q3.pdf", "url": "%s", "mime_type": "application/pdf", "size_bytes": 1200}' % REPORT["url"])


def test_noclick_itself_in_tools_whole_or_narrowed(api, client):
    create = api.post("/v1/agents").respond(json=AGENT)
    nc.Agent.create("ops", instructions="Run our account.", tools=["search", nc.Platform()])
    assert body(create.calls.last.request)["tools"] == ["search", "noclick"]
    nc.Agent.create("registrar", instructions="Keep our domains.", tools=[nc.Platform.only("domains", "read")])
    # Names go on the wire as policy names them; the API checks them.
    assert body(create.calls.last.request)["tools"] == ["noclick.domains", "noclick.read"]
    nc.Agent.create("ops", instructions="Run our account.", tools=["noclick.spend"])
    assert body(create.calls.last.request)["tools"] == ["noclick.spend"]
    assert nc.Platform.only("read") == nc.Platform.only("read") and repr(nc.Platform()) == "Platform()"
    assert repr(nc.Platform.only("read", "read")) == "Platform.only('read')"
    with pytest.raises(ValueError, match="read, build, deploy, spend, delete"):
        nc.Platform.only()


def test_files_upload_then_go_with_the_message(api, client, tmp_path):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    upload = api.post("/v1/agents/ag_1/attachments").mock(side_effect=[
        httpx.Response(201, json=CLIP), httpx.Response(201, json=REPORT)])
    send = api.post("/v1/agents/ag_1/messages").respond(202, json=operation("op_1", kind="agent.message"))
    report = tmp_path / "q3.pdf"
    report.write_bytes(b"%PDF-1.4")
    agent = nc.Agent.from_id("ag_1")
    clip = agent.upload(b"OggS...", name="question.webm", mime_type="audio/webm", voice=True)
    assert isinstance(clip, nc.Attachment) and (clip.id, clip.kind, clip.voice, clip.duration_ms) == (
        "att_2", "audio", True, 3100)
    assert dict(upload.calls.last.request.url.params) == {"name": "question.webm", "mime_type": "audio/webm",
                                                           "voice": "true"}

    agent.send("What stands out?", conversation="desk", files=[str(report), clip])
    first = upload.calls[1].request  # the path was uploaded first, named and typed from its name
    assert dict(first.url.params) == {"name": "q3.pdf", "mime_type": "application/pdf"} and first.content == b"%PDF-1.4"
    assert body(send.calls.last.request) == {"text": "What stands out?", "conversation": "desk",
                                             "attachments": ["att_1", "att_2"]}
    agent.send("And now?", conversation="desk")
    assert body(send.calls.last.request) == {"text": "And now?", "conversation": "desk"}


def test_a_stream_shows_files_approvals_and_long_actions(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.post("/v1/agents/ag_1/messages").respond(200, content=SSE.encode(),
                                                 headers={"content-type": "text/event-stream"})
    events = list(nc.Agent.from_id("ag_1").stream("Buy us a number.", conversation="desk"))
    assert [e.type for e in events] == ["file", "tool_call", "approval", "operation", "file", "done"]
    sent, _, approval, started, made, done = events
    assert (sent.role, sent.file) == ("user", nc.Attachment._from(SHOWN))
    assert sent.file.kind == "file" and sent.file.id is None and sent.file.size_bytes == 1200
    assert approval.approval["url"] == "https://noclick.com/approve/ap_1" and approval.approval["price"] == {
        "amount_usd": 1.15}
    assert started.operation == {"id": "op_2", "status": "running", "summary": "Deploy acme-site"}
    assert (made.role, made.file.name, made.file.kind) == ("assistant", "plan.md", "file")
    assert {e.operation_id for e in events} == {"op_1"} and done.reply.text == "Waiting for your approval."


def test_history_and_a_watched_message_carry_their_files(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/conversations/desk").respond(json={"messages": [
        {"role": "user", "text": "What stands out?", "created_at": "2026-10-15T10:00:00Z", "files": [
            {"name": "q3.pdf", "url": REPORT["url"], "mime_type": "application/pdf"},
            {"name": "chart.png", "url": "https://assets.example/chart.png", "mime_type": "image/png"}]},
        {"role": "assistant", "text": "Revenue doubled.", "created_at": "2026-10-15T10:00:05Z", "tool_calls": [
            {"tool": "noclick__api_call", "arguments": {"operation": "dicts_get"}, "result": '{"response": {}}',
             "is_error": False}]}]})
    first, reply = nc.Agent.from_id("ag_1").history("desk")
    assert [(f.name, f.kind) for f in first.files] == [("q3.pdf", "file"), ("chart.png", "image")]
    assert (first.tool_calls, reply.files) == ([], [])
    assert [(c["tool"], c["is_error"]) for c in reply.tool_calls] == [("noclick__api_call", False)]
    watched = ('event: message\ndata: {"role": "user", "text": "Look", "files": [{"name": "chart.png", '
               '"url": "https://assets.example/chart.png", "mime_type": "image/png"}]}\n\n'
               'event: message\ndata: {"role": "assistant", "text": "Done.", "tool_calls": [{"tool": '
               '"noclick__search", "arguments": {}, "result": "[]", "is_error": false}]}\n\n')
    api.get("/v1/agents/ag_1/conversations/desk/events").respond(200, content=watched.encode())
    asked, answered = list(nc.Agent.from_id("ag_1").watch("desk"))
    assert asked.type == "message" and [f.kind for f in asked.files] == ["image"] and asked.tool_calls == []
    assert [c["tool"] for c in answered.tool_calls] == ["noclick__search"]


def test_watching_with_replay_starts_with_whats_kept_a_coding_harnesss_output_among_it(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    watched = ('event: tool_call\ndata: {"id": "c1", "tool": "shell", "arguments": {"command": "npm test"}, '
               '"source": "harness"}\n\n'
               'event: output\ndata: {"id": "c1", "text": "ok\\n"}\n\n'
               'event: diff\ndata: {"id": "p1", "path": "src/a.py", "kind": "update", "diff": "-a\\n+b\\n"}\n\n')
    stream = api.get("/v1/agents/ag_1/conversations/task/events").respond(200, content=watched.encode())
    events = list(nc.Agent.from_id("ag_1").watch("task", replay=True))
    assert stream.calls.last.request.url.params.get("replay") == "1"
    assert [(e.type, e.text, e.call_id) for e in events] == [
        ("tool_call", None, "c1"), ("output", "ok\n", "c1"), ("diff", None, "p1")]
    assert events[0].source == "harness" and events[0].arguments == {"command": "npm test"}
    assert (events[2].path, events[2].change, events[2].diff) == ("src/a.py", "update", "-a\n+b\n")
    list(nc.Agent.from_id("ag_1").watch("task"))
    assert "replay" not in stream.calls.last.request.url.params


def test_a_coding_harnesss_command_says_how_it_ended_and_what_replaced_its_output(api, client):
    """A harness's own command ends with its exit code and time; output the stream missed comes again ``whole``,
    replacing what streamed; a new file's diff is its content; moments the sandbox couldn't send are counted."""
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    watched = ('event: output\ndata: {"id": "c1", "text": "partial"}\n\n'
               'event: output\ndata: {"id": "c1", "text": "all of it\\n", "whole": true}\n\n'
               'event: tool_result\ndata: {"id": "c1", "tool": "shell", "source": "harness", "exit_code": 1, '
               '"duration_ms": 1520, "is_error": true, "result": "exit 1"}\n\n'
               'event: diff\ndata: {"id": "p2", "path": "NOTES.md", "kind": "add", "diff": "# Notes\\n"}\n\n'
               'event: status\ndata: {"status": "events_dropped", "count": 12}\n\n')
    api.get("/v1/agents/ag_1/conversations/task/events").respond(200, content=watched.encode())
    partial, whole, ended, added, dropped = nc.Agent.from_id("ag_1").watch("task")
    assert (partial.whole, whole.whole, whole.text, whole.call_id) == (False, True, "all of it\n", "c1")
    assert (ended.call_id, ended.source, ended.exit_code, ended.duration_ms, ended.is_error) == (
        "c1", "harness", 1, 1520, True)
    assert (added.path, added.change, added.diff) == ("NOTES.md", "add", "# Notes\n")
    assert (dropped.status, dropped.count) == ("events_dropped", 12)
    # Output names no source, exit, file or count: those stay unset.
    assert (partial.source, partial.exit_code, partial.path, partial.change, partial.count) == (None,) * 5


def test_a_coding_agents_reply_keeps_its_turns_steps_in_the_shape_its_live_events_showed_them(api, client):
    """History names each message's turn; a reply's steps are its tool calls, a coding harness's own with what each
    command printed and each edit's diff. Its live events say each step's kind as the kept steps do."""
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    ran = {"id": "c1", "source": "harness", "kind": "command", "tool": "shell", "arguments": {"command": "npm test"},
           "command": "npm test", "path": None, "query": None, "output": "Tests: 1 failed\n", "exit_code": 1,
           "duration_ms": 2400, "is_error": True, "result": None, "diffs": [], "created_at": "2026-11-09T10:00:01+00:00"}
    edited = {**ran, "id": "e1", "kind": "edit", "tool": "edit", "arguments": {"path": "src/a.py"}, "command": None,
              "path": "src/a.py", "output": None, "exit_code": None, "duration_ms": None, "is_error": False,
              "diffs": [{"path": "src/a.py", "kind": "update", "diff": "@@ -1 +1 @@\n-a\n+b\n"}]}
    searched = {"tool": "search__search", "arguments": {"query": "pytest"}, "result": "two results", "is_error": False}
    api.get("/v1/agents/ag_1/conversations/task").respond(json={"messages": [
        {"role": "user", "text": "Fix the tests.", "created_at": None, "operation_id": "op_1"},
        {"role": "assistant", "text": "Fixed it.", "created_at": None, "operation_id": "op_1",
         "tool_calls": [ran, searched, edited]},
        {"role": "person", "text": "Thanks!", "created_at": None}]})
    asked, replied, thanked = nc.Agent.from_id("ag_1").history("task")
    assert (asked.operation_id, replied.operation_id, thanked.operation_id) == ("op_1", "op_1", None)
    command, tool, edit = replied.steps
    assert (command.kind, command.call_id, command.command, command.output, command.exit_code, command.duration_ms,
            command.is_error, command.created_at.isoformat()) == (
        "command", "c1", "npm test", "Tests: 1 failed\n", 1, 2400, True, "2026-11-09T10:00:01+00:00")
    assert (tool.kind, tool.tool, tool.call_id, tool.source, tool.result, tool.diffs) == (
        "tool", "search__search", None, None, "two results", [])
    assert (edit.kind, edit.path, edit.diffs) == (
        "edit", "src/a.py", [nc.AgentStepDiff("src/a.py", "update", "@@ -1 +1 @@\n-a\n+b\n")])
    assert command.raw == replied.tool_calls[0] == ran

    watched = ('event: tool_call\ndata: {"id": "g1", "tool": "Grep", "source": "harness", "kind": "search", '
               '"query": "TODO", "path": "src", "arguments": {"pattern": "TODO"}}\n\n'
               'event: tool_result\ndata: {"id": "g1", "tool": "Grep", "source": "harness", "kind": "search", '
               '"is_error": false}\n\n'
               'event: diff\ndata: {"id": "e1", "path": "src/a.py", "kind": "update", "diff": "-a\\n+b\\n"}\n\n')
    api.get("/v1/agents/ag_1/conversations/task/events").respond(200, content=watched.encode())
    events = list(nc.Agent.from_id("ag_1").watch("task"))
    assert [(e.step_kind, e.query, e.path, e.change) for e in events] == [
        ("search", "TODO", "src", None), ("search", None, None, None), (None, None, "src/a.py", "update")]

    # A turn's reply as its operation settles with it.
    api.get("/v1/operations/op_1/wait").respond(json=operation(
        "op_1", kind="agent.message", status="succeeded", result={"text": "Fixed it.", "tool_calls": [ran]}))
    reply = nc.Operation.from_id("op_1").wait()
    assert [(step.kind, step.exit_code) for step in reply.steps] == [("command", 1)]


SUMMARY = {"label": "Read 5 files, searched 5 times", "counts": {"read": 7, "search": 5, "edit": 8, "test": 3},
           "failed": 3, "changed": {"label": "Changed 2 files", "files": [
               {"path": "usage.py", "added": 0, "removed": 0, "how": ["sed", "script"]},
               {"path": "test_platform_plan_usage.py", "added": 310, "removed": 0, "how": []}],
               "added": 310, "removed": 0, "by_script": 1},
           "tests": {"passed": 161, "failed": 0, "skipped": 0, "total": 161, "done": True, "label": "161 passed"}}
GROUP = {"id": "g:s2", "label": "Read 2 files, searched for 2 patterns", "counts": {"read": 2, "search": 2, "list": 0},
         "step_ids": ["s2", "s3", "s4", "s5"], "running": False}


def test_a_coding_turns_steps_say_what_they_did_in_words_fold_and_sum_up(api, client):
    """A coding harness's step says what it did in words, judged once by NoClick: its category, its label in its tense,
    where that came from, the command as shown, a test run's counts and a count it reported, an edit's lines, whether
    it failed and the fold it's in; a reply says what its turn did and its folds, live and kept alike."""
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    read = {"id": "s3", "source": "harness", "kind": "command", "tool": "shell", "command": "sed -n 55,110p a.py",
            "arguments": {"command": "sed -n 55,110p a.py"}, "output": "x\n", "exit_code": 0, "is_error": False,
            "diffs": [], "created_at": None, "category": "read",
            "label": {"text": "Read a.py lines 55-110", "verb": "Read", "object": "a.py", "detail": "lines 55-110"},
            "label_source": "derived", "display_command": "sed -n 55,110p a.py", "lines": {"from": 55, "to": 110},
            "output_lines": 1, "failed": False, "group": "g:s2", "paths": ["a.py"]}
    tests = {**read, "id": "s26", "category": "test", "label": {"text": "Ran the plan usage tests", "verb": "Ran"},
             "label_source": "description", "group": None, "lines": None, "output_lines": 4,
             "tests": SUMMARY["tests"], "progress": {"done": 161, "total": 161}}
    edited = {**read, "id": "s15", "kind": "edit", "category": "edit", "label": {"text": "Edited usage.py"},
              "diff_stat": {"added": 3, "removed": 1}, "group": None}
    api.get("/v1/agents/ag_1/conversations/task").respond(json={"messages": [
        {"role": "assistant", "text": "Done.", "created_at": None, "operation_id": "op_1",
         "tool_calls": [read, tests, edited], "summary": SUMMARY, "groups": [GROUP]}]})
    [replied] = nc.Agent.from_id("ag_1").history("task")
    sed, ran, edit = replied.steps
    assert (sed.category, sed.label, sed.label_source, sed.display_command, sed.lines, sed.output_lines, sed.failed,
            sed.group) == ("read", nc.StepLabel("Read a.py lines 55-110", "Read", "a.py", "lines 55-110"), "derived",
                           "sed -n 55,110p a.py", {"from": 55, "to": 110}, 1, False, "g:s2")
    assert sed.paths == ["a.py"]
    assert (ran.label.text, ran.label_source, ran.tests, ran.progress) == (
        "Ran the plan usage tests", "description", nc.StepTests(161, 0, 0, 161, True, "161 passed"),
        nc.StepProgress(161, 161))
    assert edit.diff_stat == nc.DiffStat(3, 1)
    assert replied.groups == [nc.StepGroup("g:s2", GROUP["label"], GROUP["counts"], GROUP["step_ids"], False)]
    summary = replied.summary
    assert (summary.label, summary.failed, summary.counts["edit"], summary.tests.label) == (
        "Read 5 files, searched 5 times", 3, 8, "161 passed")
    assert summary.changed == nc.TurnChanges("Changed 2 files", [
        nc.ChangedFile("usage.py", 0, 0, ["sed", "script"]), nc.ChangedFile("test_platform_plan_usage.py", 310, 0, [])],
        310, 0, 1)

    import json as _json
    moments = [
        ("tool_call", {"id": "s26", "tool": "shell", "source": "harness", "kind": "command", "category": "test",
                       "label": {"text": "Running the plan usage tests", "verb": "Running"},
                       "display_command": "pytest x", "group": None, "arguments": {"command": "pytest x"}}),
        ("output", {"id": "s26", "text": "....\n", "output_lines": 3,
                    "tests": {"passed": 0, "failed": 0, "skipped": 0, "total": 161, "done": False, "label": "64 of 161"},
                    "progress": {"done": 64, "total": 161}}),
        ("group", GROUP),
        ("tool_result", {"id": "s26", "tool": "shell", "source": "harness", "kind": "command", "category": "test",
                         "label": {"text": "Ran the plan usage tests"}, "failed": False, "group": None,
                         "tests": SUMMARY["tests"], "output_lines": 4}),
        ("turn_end", {"status": "succeeded", "text": "Done.", "operation_id": "op_1", "summary": SUMMARY}),
    ]
    stream = "".join(f"event: {kind}\ndata: {_json.dumps(data)}\n\n" for kind, data in moments)
    api.get("/v1/agents/ag_1/conversations/task/events").respond(200, content=stream.encode())
    call, out, group, end, turn_end = list(nc.Agent.from_id("ag_1").watch("task"))
    assert (call.category, call.label.text, call.display_command) == ("test", "Running the plan usage tests", "pytest x")
    assert (out.progress, out.tests.label, out.output_lines) == (nc.StepProgress(64, 161), "64 of 161", 3)
    assert group.step_group == replied.groups[0]
    assert (end.label.text, end.failed, end.tests.label) == ("Ran the plan usage tests", False, "161 passed")
    assert turn_end.summary == summary

    # A turn's reply as its operation settles with it.
    api.get("/v1/operations/op_1/wait").respond(json=operation(
        "op_1", kind="agent.message", status="succeeded",
        result={"text": "Done.", "tool_calls": [read], "summary": SUMMARY, "groups": [GROUP]}))
    reply = nc.Operation.from_id("op_1").wait()
    assert (reply.summary, reply.groups) == (summary, replied.groups)


def test_a_message_says_how_it_arrived_and_a_note_carries_its_data(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    setup = {"setup": {"kind": "agent", "workflow_id": "wf_1"}}
    api.get("/v1/agents/ag_1/conversations/owner").respond(json={"messages": [
        {"role": "note", "text": "Let’s finish setting up Bakery.", "created_at": "2026-10-15T10:00:00Z",
         "data": setup},
        {"role": "user", "text": "Open Saturday?", "created_at": "2026-10-15T10:01:00Z", "via": "whatsapp"},
        {"role": "assistant", "text": "9 to 3.", "created_at": "2026-10-15T10:01:05Z"}]})
    note, texted, reply = nc.Agent.from_id("ag_1").history("owner")
    assert (note.role, note.data, note.via) == ("note", setup, None)
    assert (texted.via, reply.via, reply.data) == ("whatsapp", None, None)
    watched = 'event: message\ndata: {"role": "user", "text": "Hi", "via": "call", "operation_id": "op_1"}\n\n'
    api.get("/v1/agents/ag_1/conversations/owner/events").respond(200, content=watched.encode())
    [said] = list(nc.Agent.from_id("ag_1").watch("owner"))
    assert (said.role, said.via, said.data) == ("user", "call", None)


def test_a_note_joins_a_conversation_once_by_its_key(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    add = api.post("/v1/agents/ag_1/conversations/owner/notes").mock(side_effect=[
        httpx.Response(201, json={"object": "note", "added": True}),
        httpx.Response(201, json={"object": "note", "added": False})])
    agent = nc.Agent.from_id("ag_1")
    data = {"setup": {"kind": "mcp", "workflow_id": "wf_1"}}
    assert agent.note("owner", "Let’s finish setting up Bakery.", data=data, key="setup:wf_1") is True
    assert body(add.calls.last.request) == {"text": "Let’s finish setting up Bakery.", "data": data,
                                            "key": "setup:wf_1"}
    assert agent.note("owner", "Let’s finish setting up Bakery.", data=data, key="setup:wf_1") is False


def test_the_accounts_files_list_and_go_with_a_message(api, client):
    made = {"object": "attachment", "id": "res_1", "name": "cake.png", "mime_type": "image/png", "size_bytes": 900,
            "kind": "image", "voice": False, "url": "https://assets.example/u/account/res_1/cake.png",
            "duration_ms": None, "peaks": None, "created_at": "2026-10-15T09:00:00+00:00"}
    listed = api.get("/v1/attachments").respond(json={"object": "list", "data": [made], "next_cursor": None})
    [cake] = nc.attachments(query="cake", limit=5)
    assert dict(listed.calls.last.request.url.params) == {"query": "cake", "limit": "5"}
    assert (cake.id, cake.kind, cake.url) == ("res_1", "image", made["url"])
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    send = api.post("/v1/agents/ag_1/messages").respond(202, json=operation("op_1", kind="agent.message"))
    nc.Agent.from_id("ag_1").send("Use this on the menu.", conversation="owner", files=[cake])
    assert body(send.calls.last.request)["attachments"] == ["res_1"]


def test_a_turn_shows_its_reasoning_compaction_and_its_long_actions_progress(api, client):
    import json

    api.get("/v1/agents/ag_1").respond(json=AGENT)
    progress = {"step": None, "stages": [{"name": "Queued", "status": "done", "started_at": "2026-10-15T10:00:00Z",
                                          "ended_at": "2026-10-15T10:00:03Z"},
                                         {"name": "Building", "status": "current", "started_at": "2026-10-15T10:00:03Z",
                                          "ended_at": None}],
                "lines": ["$ npm ci", "$ vite build"], "line_count": 14, "updated_at": "2026-10-15T10:00:21Z"}
    sse = ('event: status\ndata: {"status": "compacting", "created_at": "2026-10-15T09:59:00Z", "operation_id": "op_1"}'
           '\n\nevent: reasoning\ndata: {"text": "Diagnosing workflow issues", "created_at": "2026-10-15T09:59:40Z", '
           '"operation_id": "op_1"}\n\n'
           'event: operation\ndata: {"operation": {"id": "op_2", "kind": "project.deploy", "status": "running", '
           '"summary": "Deploy acme-site", "progress": %s}, "operation_id": "op_1"}\n\n'
           'event: done\ndata: {"text": "Deploying.", "conversation": "desk", "operation_id": "op_1"}\n\n'
           ) % json.dumps(progress)
    api.post("/v1/agents/ag_1/messages").respond(200, content=sse.encode(),
                                                 headers={"content-type": "text/event-stream"})
    compacting, thought, deploying, _ = list(nc.Agent.from_id("ag_1").stream("Deploy it.", conversation="desk"))
    assert (compacting.type, compacting.status) == ("status", "compacting")
    assert (thought.type, thought.text) == ("reasoning", "Diagnosing workflow issues")
    assert deploying.operation["progress"]["lines"][-1] == "$ vite build"
    api.get("/v1/agents/ag_1/conversations/desk").respond(json={"messages": [
        {"role": "assistant", "text": "Deploying.", "created_at": "2026-10-15T10:00:00Z",
         "reasoning": [{"text": "Diagnosing workflow issues", "created_at": "2026-10-15T09:59:40Z"}]}]})
    [reply] = nc.Agent.from_id("ag_1").history("desk")
    assert reply.reasoning == [{"text": "Diagnosing workflow issues", "created_at": "2026-10-15T09:59:40Z"}]
    api.get("/v1/operations/op_2").respond(json=operation("op_2", kind="project.deploy", status="running",
                                                          progress=progress))
    op = nc.Operation.from_id("op_2")
    assert [s["status"] for s in op.progress["stages"]] == ["done", "current"] and op.progress["line_count"] == 14

"""The command spec both CLIs run from, and the commands made from it: one per /v1 operation, `noclick api`,
`noclick describe`, `noclick help --json`, and how every command answers and exits."""

import json
import sys
from pathlib import Path

import httpx
import pytest

from noclick import cli
from noclick._cli import output, screens
from noclick._cli.commands import commands_for, example, shadowed
from noclick._cli.spec import load
from platform_helpers import BASE, body, operation

AGENT = "3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b40"  # an id NoClick made: anything else is a name, read from a list first

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cli_manifest  # noqa: E402


@pytest.fixture
def home(monkeypatch, tmp_path, client):
    monkeypatch.setenv("NOCLICK_API_KEY", "nk_live_test")
    monkeypatch.setenv("NOCLICK_API_URL", BASE)
    monkeypatch.setenv("NOCLICK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr("noclick._cli.commands.WAIT_WINDOW_S", 1)


def test_the_manifest_is_the_curated_commands_the_parser_has():
    assert cli_manifest.main([]) == 0, "run python scripts/cli_manifest.py --write"
    paths = [tuple(c["path"]) for c in load().commands]
    assert len(paths) == len(set(paths))
    assert {("deploy",), ("api",), ("describe",), ("help",)} <= set(paths)


def test_every_area_parses_and_every_operation_is_a_command_of_its_own():
    spec = load()
    for area, ops in spec.areas().items():
        parser = cli.build_parser([area])
        for op in ops:
            if shadowed(op):  # the curated command of that name runs
                assert example(op).startswith("noclick api ")
                continue
            words = [area, op["command"], *(f"x{i}" for i, p in enumerate(op["params"]) if p["in"] == "path")]
            args = parser.parse_args(words)
            # A curated command of the same name (agents list) is the curated one; the rest run their operation.
            if getattr(args, "operation_spec", None) is not None:
                assert args.operation_spec["name"] == op["name"]


def test_a_generated_command_answered_with_a_file_prints_its_bytes_or_saves_them(home, api, capfdbinary, tmp_path):
    """A command reading a file (a sandbox's) prints what the API sent as it is, not as JSON, and --output saves it."""
    op = load().for_call("GET", "/v1/sandboxes/{sandbox_id}/files")
    reads = api.get("/v1/sandboxes/sb_1/files")
    words = ["sandboxes", op["command"], "sb_1", "--path", "notes.txt"]
    reads.respond(200, content=b"two\nlines, no newline at the end", headers={"content-type": "text/plain"})
    assert cli.main(words) == output.OK
    assert capfdbinary.readouterr().out == b"two\nlines, no newline at the end"
    picture = bytes(range(256))
    reads.respond(200, content=picture, headers={"content-type": "application/octet-stream"})
    saved = tmp_path / "logo.png"
    assert cli.main([*words, "--output", str(saved)]) == output.OK
    assert saved.read_bytes() == picture and capfdbinary.readouterr().out == f"{saved}\n".encode()
    # A JSON answer is still JSON, saved as JSON with --output.
    reads.respond(200, json={"path": "notes.txt"})
    assert cli.main([*words, "--output", str(saved)]) == output.OK
    assert json.loads(saved.read_text()) == {"path": "notes.txt"}


def test_a_generated_command_makes_its_call_with_path_query_and_body(home, api, capsys):
    route = api.post(f"/v1/agents/{AGENT}/messages").mock(
        return_value=httpx.Response(200, json={"id": "msg_1", "url": "https://noclick.test/m/1"}))
    code = cli.main(["agents", "messages-create", AGENT, "--text", "hi", "--attachments", "a1",
                     "--attachments", "a2", "--data", '{"conversation": "c1", "text": "replaced"}'])
    assert code == output.OK
    assert body(route.calls.last.request) == {"text": "hi", "attachments": ["a1", "a2"], "conversation": "c1"}
    # Its useful value alone on the last line.
    assert capsys.readouterr().out.splitlines()[-1] == "https://noclick.test/m/1"


def test_a_required_field_left_out_is_a_usage_error_naming_the_flag_and_how_to_learn_more(home, api, capsys):
    assert cli.main(["agents", "create", "--name", "x", "--json"]) == output.USAGE
    error = json.loads(capsys.readouterr().out)["error"]
    assert "--instructions" in error["message"]
    assert error["next_step"] == "noclick describe agents create"
    assert not api.calls


def test_an_operation_it_starts_is_waited_on_and_one_waiting_on_a_person_exits_3(home, api, capsys):
    api.post(f"/v1/agents/{AGENT}/messages").mock(
        return_value=httpx.Response(202, json=operation("op_9", status="running")))
    api.get("/v1/operations/op_9/wait").mock(return_value=httpx.Response(200, json=operation(
        "op_9", status="awaiting_human", result={"url": "https://noclick.test/h/1"})))
    api.get("/v1/operations/op_9").mock(return_value=httpx.Response(200, json=operation("op_9", status="awaiting_human")))
    assert cli.main(["agents", "messages-create", AGENT, "--text", "hi"]) == output.WAITING
    assert capsys.readouterr().out.splitlines()[-1] == "https://noclick.test/h/1"

    assert cli.main(["agents", "messages-create", AGENT, "--text", "hi", "--no-wait", "--json"]) == output.OK
    assert json.loads(capsys.readouterr().out)["status"] == "running"


@pytest.mark.parametrize("status, error_type, code", [
    (402, "approval_required", output.WAITING),
    (402, "spend_cap_exceeded", output.REFUSED),
    (403, "policy_denied", output.REFUSED),
    (400, "invalid_request", output.USAGE),
    (404, "not_found", output.FAILED),
])
def test_an_api_refusal_exits_by_what_it_is_and_names_the_next_command(home, api, capsys, status, error_type, code):
    api.get(f"/v1/agents/{AGENT}").mock(return_value=httpx.Response(status, json={"error": {
        "type": error_type, "message": "No.", "next_step": "List agents with GET /v1/agents.",
        "approve_url": "https://noclick.test/approve/1"}}))
    assert cli.main(["agents", "get", AGENT, "--json"]) == code
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["type"] == error_type and error["exit_code"] == code
    # The route it names is said as the command that makes it.
    assert error["next_step"] == "List agents with noclick agents list."
    assert error["commands"] == ["noclick agents list"]
    assert cli.main(["agents", "get", AGENT]) == code
    said = capsys.readouterr().err
    assert "  next step: List agents with noclick agents list." in said and "  run:" not in said  # said once


def test_api_calls_any_route_through_the_sdk(home, api, capsys):
    route = api.patch("/v1/agents/a1").mock(return_value=httpx.Response(200, json={"id": "a1", "name": "b"}))
    assert cli.main(["api", "patch", "/v1/agents/a1", "--data", '{"name": "b"}', "-q", "user_id=u1", "--json"]) == 0
    assert body(route.calls.last.request) == {"name": "b"}
    assert route.calls.last.request.url.params["user_id"] == "u1"
    assert json.loads(capsys.readouterr().out) == {"id": "a1", "name": "b"}


def test_describe_and_help_say_every_command_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("NOCLICK_API_KEY", raising=False)
    assert cli.main(["describe", "POST", "/v1/agents/a1/messages", "--json"]) == 0
    described = json.loads(capsys.readouterr().out)
    assert described["name"] == "agents_messages_create"
    assert described["example"] == "noclick agents messages-create <agent_id>"

    assert cli.main(["help", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert len(listed["operations"]) == len(load().operations)
    assert {"deploy"} <= {" ".join(c["path"]) for c in listed["commands"]}
    assert listed["conventions"]["exit_codes"]["3"] == "waiting on a person"


def test_an_api_route_a_next_step_names_is_the_command_that_makes_it_and_nothing_is_read_out_of_its_words():
    commands = commands_for(load())
    assert commands.routes("Read it again: GET /v1/workflows/{id}/approvals/{approval_id}.") == [
        "noclick workflows approvals-get <workflow_id> <approval_id>"]
    # Commands written in words are a person's to read: what to run comes from fields, never parsed out of prose.
    assert commands.routes("Run noclick link x --create makes it (and its repo).") == []
    error = output.run(cli.CommandError("x", next_step="noclick link x --create makes it."), ["noclick link x --create"])
    assert output.error_body(error, commands)["commands"] == ["noclick link x --create"]
    from noclick.exceptions import Conflict
    served = Conflict("y", next_step="See GET /v1/agents.", details={"run": ["noclick agents list"]})
    # The API's own (details.run), then the route its step names: the same command, said once.
    assert output.error_body(served, commands)["commands"] == ["noclick agents list"]
    assert commands.for_call("GET", "/v1/domains/search") == "noclick domains search <query>"  # curated, with its argument
    assert "run" not in output.error_body(served, commands).get("details", {})


ROOT = Path(__file__).resolve().parents[1]
SOURCES = [*(ROOT / "noclick").glob("cli.py"), *(ROOT / "noclick" / "_cli").rglob("*.py"),
           *(ROOT.parent / "typescript" / "src" / "cli").rglob("*.ts")]


def _closing(text: str, start: int) -> int:
    """Where the bracket opened at ``start`` closes, past strings."""
    depth, i, quote = 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError(f"unclosed bracket at {start}")


def _run_lists(text: str):
    """Each list of commands an error is raised with: ``run=[...]``, ``output.run(err, [...])``,
    ``withRun(err, [...])`` and UsageError's third argument."""
    import re

    for found in re.finditer(r"\brun=\[", text):
        yield text[found.end() - 1:_closing(text, found.end() - 1) + 1]
    for found in re.finditer(r"\b(?:output\.run|out\.run|withRun|new UsageError)\(", text):
        call = text[found.end() - 1:_closing(text, found.end() - 1) + 1]
        lists = [m.end() - 1 for m in re.finditer(r",\s*\[", call)]
        if lists and call[:_closing(call, lists[-1]) + 1].rstrip().endswith("]"):
            yield call[lists[-1]:_closing(call, lists[-1]) + 1]


def _commands_in(listed: str):
    """The command lines a list literal holds, each placeholder (``{name}``, ``${name}``, ``<name>``) a value."""
    import re

    for literal in re.findall(r"f?\"((?:[^\"\\]|\\.)*)\"|f?'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`", listed):
        text = next(part for part in literal if part)
        text = re.sub(r"\$?\{[^}]*(?:prog|usage)\}", "noclick deploy", text)  # the command the mistake was in
        text = re.sub(r"\$?\{[^}]*\}", "x", text)
        yield re.sub(r"<[^>]+>", "x", text)


def _parses(command: str, parsers: dict) -> None:
    import shlex

    words = shlex.split(command)
    assert words[0] == "noclick", command
    argv = cli._unaliased(words[1:])
    parser = parsers.get(argv[0]) or parsers.setdefault(argv[0], cli.build_parser(argv))  # one per area
    try:
        parser.parse_args(argv)
    except SystemExit as stopped:
        if stopped.code:
            raise AssertionError(f"run: {command} isn't a command line noclick takes") from stopped


def test_every_run_line_an_error_can_print_is_a_command_line_noclick_takes():
    """Each ``run:`` an error prints is a whole command, run as it is: those both CLIs raise errors with, those the
    command line says for what isn't there (``screens.MAKES``, ``MADE_BY``), and the command for every API route."""
    found = {c for path in SOURCES for listed in _run_lists(path.read_text()) for c in _commands_in(listed)}
    assert len(found) > 30 and all(c.startswith("noclick ") for c in found), found  # every error site's, both CLIs'
    found |= {made.format(name="x") for _, made in screens.MAKES.values()}
    spec = load()
    for route in screens.MADE_BY.values():
        op = spec.for_call("POST", route)
        assert op is not None and not shadowed(op), route
        found.add(output.command_line(op, op["path"]))
    routes = commands_for(spec)
    found |= {routes.for_call(op["method"], op["path"]) for op in spec.operations}
    parsers: dict = {}
    for command in sorted(found):
        _parses(command.replace("<", "").replace(">", ""), parsers)
    # An operation a step names is its command too; in its words, each route and operation is said as its command.
    commands = routes
    assert commands.routes("Call agents_update with a new name.") == ["noclick agents update <agent_id>"]
    # In its words, each route and operation it names is the command, its query the flags that set it.
    assert commands.translate("Use an id from GET /v1/machines?limit=5&name=build%20box (a user's are theirs).") == (
        "Use an id from noclick machines list --limit 5 --name 'build box' (a user's are theirs).")
    assert commands.translate("Read the file with GET /v1/sandboxes/sb_1/files.") == (
        "Read the file with noclick sandboxes files-read sb_1.")
    assert commands.translate("Call `agents_update` with a new name.") == (
        "Call `noclick agents update <agent_id>` with a new name.")
    assert commands.translate("Ask again with GET /v1/nothing/here.") == (
        "Ask again with noclick api GET /v1/nothing/here.")


def test_a_command_is_named_for_what_it_does_and_its_old_name_still_runs_it(monkeypatch, capsys):
    spec = load()
    # A file's bytes are read and written, a POST that lists is named for what it returns, the area isn't said twice.
    named = {op["name"]: f"{op['area']} {op['command']}" for op in spec.operations}
    assert named["sandboxes_files_list"] == "sandboxes files-read"
    assert named["sandboxes_files_replace"] == "sandboxes files-write"
    assert named["usage_charges_create"] == "usage charges"
    assert named["usage"] == "usage summary"
    assert named["machines_list"] == "machines list" and named["machines_get"] == "machines get"
    assert not any(op["command"] == op["area"] or op["command"].endswith(("-post", "-replace"))
                   for op in spec.operations)
    # Every command it had before keeps running the same operation, though no list shows it.
    kept = json.loads((Path(__file__).parent / "fixtures" / "cli_names_before.json").read_text())
    assert len(kept) > 800
    for area, command, name in kept:
        assert spec.find(area, command)["name"] == name, f"noclick {area} {command}"
    monkeypatch.delenv("NOCLICK_API_KEY", raising=False)
    assert cli.main(["describe", "usage", "charges-create"]) == 0
    assert capsys.readouterr().out.startswith("noclick usage charges   (usage_charges_create)")
    assert cli.main(["usage"]) == 0
    listed = capsys.readouterr().out
    assert "noclick usage charges " in listed and "charges-create" not in listed
    with pytest.raises(SystemExit):
        cli.main(["usage", "chargez"])
    assert "Did you mean: usage charges?" in capsys.readouterr().err


def test_a_name_given_for_an_id_is_read_from_its_list(home, api, capsys):
    machines = api.get("/v1/machines", params={"name": "build box"}).respond(json={"object": "list", "data": [
        {"object": "machine", "id": AGENT, "name": "build box", "status": "running"},
        {"object": "machine", "id": "other", "name": "build box 2", "status": "running"}], "next_cursor": None})
    got = api.get(f"/v1/machines/{AGENT}").respond(json={"object": "machine", "id": AGENT, "name": "build box"})
    assert cli.main(["machines", "get", "build box", "--json"]) == output.OK
    assert machines.called and got.called and json.loads(capsys.readouterr().out)["id"] == AGENT
    # An id goes as it is, read from no list.
    assert cli.main(["machines", "get", AGENT]) == output.OK and machines.call_count == 1
    capsys.readouterr()

    # None by that name: it says so, and how to list them.
    api.get("/v1/machines", params={"name": "nope"}).respond(json={"object": "list", "data": [], "next_cursor": None})
    assert cli.main(["machines", "get", "nope"]) == output.FAILED
    said = capsys.readouterr().err
    assert "error: No machine named 'nope'." in said and "  next step: List them with noclick machines list." in said
    assert "  run:" not in said  # the next step ends with it: said once

    # Two by that name: each is listed, and nothing is called with either.
    twins = [{"object": "machine", "id": f"3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b4{i}", "name": "web", "status": s}
             for i, s in ((1, "running"), (2, "stopped"))]
    api.get("/v1/machines", params={"name": "web"}).respond(json={"object": "list", "data": twins, "next_cursor": None})
    assert cli.main(["machines", "delete", "web", "--json"]) == output.USAGE
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["message"] == ("2 machines are named 'web': 3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b41 (running), "
                                "3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b42 (stopped).")
    assert [m["id"] for m in error["details"]["matches"]] == [t["id"] for t in twins]

    # A nested argument is read from its parent's list, the parent read first.
    api.get("/v1/agents", params={"name": "support"}).respond(json={"object": "list", "data": [
        {"object": "agent", "id": AGENT, "name": "helpdesk", "former_names": ["support"]}], "next_cursor": None})
    triggers = api.get(f"/v1/agents/{AGENT}/triggers").respond(json={"object": "list", "data": [
        {"object": "trigger", "id": "3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b49", "name": "nightly"}], "next_cursor": None})
    paused = api.post(f"/v1/agents/{AGENT}/triggers/3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b49/pause").respond(
        json={"object": "trigger", "id": "3b9e2c71-4f0d-4a68-9c15-7e2a8d1f6b49", "status": "paused"})
    assert cli.main(["agents", "triggers-pause", "support", "nightly"]) == output.OK
    assert triggers.called and paused.called

"""The command spec both CLIs run from, and the commands made from it: one per /v1 operation, `noclick api`,
`noclick describe`, `noclick help --json`, and how every command answers and exits."""

import json
import sys
from pathlib import Path

import httpx
import pytest

from noclick import cli
from noclick._cli import output
from noclick._cli.commands import commands_for, example, shadowed
from noclick._cli.spec import load
from platform_helpers import BASE, body, operation

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


def test_a_generated_command_makes_its_call_with_path_query_and_body(home, api, capsys):
    route = api.post("/v1/agents/support%20bot/messages").mock(
        return_value=httpx.Response(200, json={"id": "msg_1", "url": "https://noclick.test/m/1"}))
    code = cli.main(["agents", "messages-create", "support bot", "--text", "hi", "--attachments", "a1",
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
    api.post("/v1/agents/a1/messages").mock(return_value=httpx.Response(202, json=operation("op_9", status="running")))
    api.get("/v1/operations/op_9/wait").mock(return_value=httpx.Response(200, json=operation(
        "op_9", status="awaiting_human", result={"url": "https://noclick.test/h/1"})))
    api.get("/v1/operations/op_9").mock(return_value=httpx.Response(200, json=operation("op_9", status="awaiting_human")))
    assert cli.main(["agents", "messages-create", "a1", "--text", "hi"]) == output.WAITING
    assert capsys.readouterr().out.splitlines()[-1] == "https://noclick.test/h/1"

    assert cli.main(["agents", "messages-create", "a1", "--text", "hi", "--no-wait", "--json"]) == output.OK
    assert json.loads(capsys.readouterr().out)["status"] == "running"


@pytest.mark.parametrize("status, error_type, code", [
    (402, "approval_required", output.WAITING),
    (402, "spend_cap_exceeded", output.REFUSED),
    (403, "policy_denied", output.REFUSED),
    (400, "invalid_request", output.USAGE),
    (404, "not_found", output.FAILED),
])
def test_an_api_refusal_exits_by_what_it_is_and_names_the_next_command(home, api, capsys, status, error_type, code):
    api.get("/v1/agents/a1").mock(return_value=httpx.Response(status, json={"error": {
        "type": error_type, "message": "No.", "next_step": "List agents with GET /v1/agents.",
        "approve_url": "https://noclick.test/approve/1"}}))
    assert cli.main(["agents", "get", "a1", "--json"]) == code
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["type"] == error_type and error["exit_code"] == code
    assert error["commands"] == ["noclick agents list"]
    assert cli.main(["agents", "get", "a1"]) == code
    assert "  run: noclick agents list" in capsys.readouterr().err


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


def test_a_next_step_naming_a_command_or_an_operation_is_the_command_that_makes_it():
    commands = commands_for(load())
    assert commands.runnable("Read it again: GET /v1/workflows/{id}/approvals/{approval_id}.") == [
        "noclick workflows approvals-get <workflow_id> <approval_id>"]
    assert commands.runnable("Run noclick login, or set NOCLICK_API_KEY.") == ["noclick login"]
    assert commands.runnable("Call agents_update with a new name.") == ["noclick agents update <agent_id>"]

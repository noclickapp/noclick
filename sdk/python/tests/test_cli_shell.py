"""``noclick shell``: one command run in a sandbox, on a machine, beside an agent or in an app's live container, its
output and exit code as the command's own; a terminal needs one, and says so."""

import json

import pytest

from noclick import cli
from platform_helpers import BASE, body, listing

SANDBOX = "3b9d6f2e-1c4a-4e8b-9f7d-2a6c5e8b1d40"


@pytest.fixture
def signed_in(monkeypatch, tmp_path, client):
    monkeypatch.setenv("NOCLICK_API_KEY", "nk_live_test")
    monkeypatch.setenv("NOCLICK_API_URL", BASE)
    monkeypatch.setenv("NOCLICK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("NOCLICK_PROFILE", raising=False)


def test_a_command_runs_where_it_says_and_exits_with_its_own_code(signed_in, api, capsys):
    ran = api.post(f"/v1/sandboxes/{SANDBOX}/exec").respond(json={
        "object": "sandbox_exec", "stdout": "Python 3.12.7\n", "stderr": "warning: old pip\n", "exit_code": 3})
    assert cli.main(["shell", SANDBOX, "--", "python", "-c", "print('hi there')"]) == 3
    assert body(ran.calls.last.request) == {"command": "python -c 'print('\"'\"'hi there'\"'\"')'"}
    out = capsys.readouterr()
    assert out.out == "Python 3.12.7\n" and out.err == "warning: old pip\n"

    api.get("/v1/projects").respond(json=listing({"object": "project", "id": "prj_1", "name": "shop"}))
    live = api.post("/v1/projects/prj_1/live/exec").respond(json={
        "stdout": "4 passed\n", "stderr": "", "exit_code": 0, "timed_out": False, "ms": 900, "vite": []})
    assert cli.main(["shell", "--app", "shop", "--json", "--", "npm test"]) == 0
    assert body(live.calls.last.request)["command"] == "npm test"
    assert json.loads(capsys.readouterr().out) == {"stdout": "4 passed\n", "stderr": "", "exit_code": 0}


def test_a_terminal_needs_one_and_an_apps_container_takes_commands_only(signed_in, api, capsys):
    assert cli.main(["shell", SANDBOX]) == 1
    err = capsys.readouterr().err
    assert "noclick shell needs a terminal to open one" in err and f"noclick shell {SANDBOX} -- <command>" in err
    assert cli.main(["shell", "--app", "shop"]) == 1
    assert "noclick shell --app shop -- <command>" in capsys.readouterr().err
    assert cli.main(["shell", "--machine", "box", "--agent", "coder", "--", "ls"]) == 1
    assert "Name one place" in capsys.readouterr().err

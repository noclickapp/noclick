"""The CLI's start, operate and teach commands: setup, init, live, wait, logs' filters, estimate by kind, docs,
skill, help --json and mcp. Each runs its real client calls against the mocked API."""

import io
import json
import sys

import httpx
import pytest

from noclick import cli
from noclick._cli import exits, link
from platform_helpers import BASE, body, listing, operation
from test_cli import DEPLOYMENT, PROJECT, SHA, FakeGit, home, run, stop_after  # noqa: F401

REPO = {"object": "repo", "id": "repo_1", "name": "booking"}
SESSION = {"id": "ls_1", "project_id": "prj_1", "state": "live", "mode": "vite", "url": "https://booking.noclick.site",
           "enter_url": "https://booking.noclick.site/__noclick/live/enter?t=x", "workdir": "/site",
           "edits": {"count": 2, "hot": 2}, "git": {"branch": "noclick-live", "head": SHA}}
PRICED = {"object": "estimate", "monthly_usd": 0.12, "lines": [], "items": []}


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- setup and init -----------------------------------------------------------


def test_setup_redeems_a_code_and_keeps_the_key_like_login(home, api, monkeypatch, capsys):
    monkeypatch.delenv("NOCLICK_API_KEY")
    api.post("/v1/setup").respond(json={"object": "setup_key", "key": "nk_live_FAKESETUP0001", "key_id": "key_3",
                                        "key_name": "Coding agent", "key_prefix": "nk_live_FAKE",
                                        "email": "ana@acme.test"})
    assert run("setup", "nc_setup_abc", "--store", "file") == 0
    out = capsys.readouterr()
    assert "Signed in as ana@acme.test." in out.out and "FAKESETUP" not in out.out + out.err
    assert cli.resolve_credentials("default").key == "nk_live_FAKESETUP0001"
    api.post("/v1/setup").respond(410, json={"error": {"type": "expired", "message": "This setup code was already "
                                                       "used or has expired.", "next_step": "Copy a new prompt."}})
    assert run("setup", "nc_setup_abc") == exits.FAILED


def test_init_from_a_template_makes_the_app_and_links_the_folder(home, api, here, monkeypatch, capsys):
    git = FakeGit()
    monkeypatch.setattr(cli, "_git", git)
    api.get("/v1/repos").respond(json=listing())
    made_repo = api.post("/v1/repos").respond(201, json=REPO)
    api.get("/v1/projects").respond(json=listing())
    made_app = api.post("/v1/projects").respond(201, json=PROJECT)
    assert run("init", "booking", "--template", "worker") == 0
    assert body(made_repo.calls.last.request)["name"] == "booking"
    assert body(made_app.calls.last.request) == {"name": "booking", "repo_id": "repo_1"}
    assert json.loads((here / "wrangler.jsonc").read_text())["main"] == "src/index.js"
    assert '"name": "booking"' in (here / "wrangler.jsonc").read_text()
    assert "export default" in (here / "src" / "index.js").read_text()
    assert link.find(here).app == "booking" and ("init", "--quiet", "--initial-branch", "main") in [
        a for a, _ in git.calls]
    assert capsys.readouterr().out == "booking\n"
    # Never over a file that's there.
    assert run("init", "booking", "--template", "worker") == exits.FAILED
    assert run("init", "booking", "--template", "nope") == exits.FAILED


def test_init_describe_hands_it_to_the_coding_agent_and_checks_its_draft_out(home, api, here, monkeypatch, capsys):
    git = FakeGit()
    git.outputs["rev-parse HEAD"] = SHA
    monkeypatch.setattr(cli, "_git", git)
    api.get("/v1/repos").respond(json=listing(REPO))
    api.get("/v1/projects").respond(json=listing(PROJECT))
    api.get("/v1/projects/prj_1").respond(json=PROJECT)
    api.get("/v1/repos/repo_1").respond(json=REPO)
    clone = api.post("/v1/repos/repo_1/clone_url").respond(json={"url": "https://x:tok@git.noclick.test/b.git"})
    handed = api.post("/v1/projects/prj_1/live/changes").respond(202, json=operation(
        "op_c", kind="agent.message", status="succeeded",
        result={"text": "Made a booking page.", "conversation": "code", "tool_calls": [],
                "code": {"branch": "noclick-code", "commits": [SHA]}}))
    assert run("init", "--describe", "a page that takes bookings", "booking") == 0
    assert body(handed.calls.last.request) == {"text": "a page that takes bookings", "title": "Draft booking"}
    assert body(clone.calls.last.request) == {"write": False, "ttl_s": 600}
    fetch = [(a, e) for a, e in git.calls if a[0] == "fetch"]
    assert fetch[0][0][-1] == "refs/heads/noclick-code" and "tok" not in " ".join(fetch[0][0])
    out = capsys.readouterr()
    assert "Made a booking page." in out.err and out.out == "booking\n"


# --- live ---------------------------------------------------------------------


def _live_routes(api):
    api.get("/v1/projects").respond(json=listing({**PROJECT, "live_editing": False}))
    api.post("/v1/estimates").respond(json=PRICED)
    api.get("/v1/projects/prj_1/live").respond(json={"enabled": False, "supported": True, "session": None})
    switched = api.patch("/v1/projects/prj_1").respond(json={**PROJECT, "live_editing": True})
    started = api.post("/v1/projects/prj_1/live/sessions").respond(json=SESSION)
    return switched, started


def test_live_starts_a_session_bounded_by_max_usd_and_prints_its_link(home, api, here, capsys):
    link.write("booking")
    switched, started = _live_routes(api)
    assert run("live", "--hours", "2", "--max-usd", "1") == 0
    assert body(switched.calls.last.request) == {"live_editing": True}
    assert body(started.calls.last.request) == {"wait": True, "limits": {"max_session_s": 7200}}
    out = capsys.readouterr()
    assert out.out == SESSION["enter_url"] + "\n"
    assert "costs about $0.12 at most" in out.err and "noclick live push" in out.err
    # Over the ceiling, nothing starts.
    assert run("live", "start", "--max-usd", "0.01") == exits.REFUSED and started.call_count == 1


def test_live_push_and_end_ship_what_was_edited(home, api, here, monkeypatch, capsys):
    link.write("booking")
    git = FakeGit()
    monkeypatch.setattr(cli, "_git", git)
    api.get("/v1/projects").respond(json=listing(PROJECT))
    api.post("/v1/repos/repo_1/clone_url").respond(json={"url": "https://x:tok@git.noclick.test/b.git"})
    assert run("live", "push") == 0
    assert [a for a, _ in git.calls if a[0] == "push"] == [("push", "noclick-deploy", "HEAD:refs/heads/noclick-live")]
    ended = api.post("/v1/projects/prj_1/live/end").respond(202, json=operation(
        "op_e", kind="project.live_end", status="succeeded",
        result={"outcome": "deployed", "session_id": "ls_1", "deployment_id": "dep_1"}))
    api.get("/v1/deployments/dep_1").respond(json=DEPLOYMENT)
    capsys.readouterr()
    assert run("live", "end") == 0
    assert body(ended.calls.last.request) == {"deploy": True}
    out = capsys.readouterr()
    assert "Deployed" in out.err and out.out == "https://booking.noclick.site\n"


# --- wait ---------------------------------------------------------------------


def test_wait_never_waits_on_a_person_and_says_where_they_act(home, api, capsys):
    api.get("/v1/operations/op_h").respond(json=operation(
        "op_h", kind="workflow.build", status="awaiting_human",
        question={"text": "Which calendar?", "answer_url": "https://noclick.test/h/q1"}))
    assert run("wait", "op_h") == exits.WAITING
    err = capsys.readouterr().err
    assert "waits on a person: Which calendar?" in err and "https://noclick.test/h/q1" in err


def test_wait_prints_the_result_or_runs_out_its_timeout(home, api, monkeypatch, capsys):
    api.get("/v1/operations/op_1").respond(json=operation("op_1", kind="agent.message", status="succeeded",
                                                          result={"text": "Done.", "conversation": "c"}))
    api.get("/v1/operations/op_1/wait").respond(json=operation(
        "op_1", kind="agent.message", status="succeeded", result={"text": "Done.", "conversation": "c"}))
    assert run("wait", "op_1") == 0 and capsys.readouterr().out == "Done.\n"
    clock = iter([0.0, 5.0, 11.0, 20.0])
    monkeypatch.setattr(cli, "_clock", lambda: next(clock))
    api.get("/v1/operations/op_r").mock(side_effect=[
        httpx.Response(200, json=operation("op_r", kind="x.y", status="running", updated_at=f"2026-09-25T10:00:0{i}Z"))
        for i in range(5)])
    assert run("wait", "op_r", "--timeout", "10") == exits.TIMED_OUT


# --- logs, estimate -------------------------------------------------------------


def test_logs_grep_json_and_a_followed_timeout(home, api, here, monkeypatch, capsys):
    link.write("booking")
    api.get("/v1/projects").respond(json=listing(PROJECT))
    lines = [{"at": f"2026-09-28T10:00:0{i}Z", "level": "error" if i % 2 else "info", "message": m,
              "deployment_id": "dep_1", "request_id": f"r{i}", "environment": "production"}
             for i, m in enumerate(["GET /", "POST /book 500", "GET /about", "POST /book 502"])]
    logs = api.get("/v1/projects/prj_1/logs").respond(json=listing(*lines))
    assert run("logs", "--grep", "book", "--json", "--limit", "1") == 0
    assert logs.calls.last.request.url.params["limit"] == str(cli.MAX_LOG_READ)  # filtered here, from all it reads
    out = capsys.readouterr()
    assert [json.loads(row)["message"] for row in out.out.splitlines()] == ["POST /book 502"]
    assert json.loads(out.out)["request_id"] == "r3" and "Showing 1 of 2 lines that match" in out.err

    clock = iter([0.0, 1.0, 2.0, 61.0])
    monkeypatch.setattr(cli, "_clock", lambda: next(clock))
    monkeypatch.setattr(cli, "_sleep", lambda s: None)
    assert run("logs", "-f", "--timeout", "60") == 0  # it stops by itself


def test_estimate_prices_one_kind_from_the_command_line(home, api, capsys):
    priced = api.post("/v1/estimates").respond(json={"object": "estimate", "monthly_usd": 1.2, "lines": [],
                                                     "items": []})
    assert run("estimate", "live_editing", "--usage", "hours=40", "--usage", "cpu_share=0.5") == 0
    assert body(priced.calls.last.request) == {"items": [{"kind": "live_editing",
                                                          "usage": {"hours": 40.0, "cpu_share": 0.5}}]}
    assert run("estimate", "project", "--option", "runtime=container", "--usage", "requests=lots") == exits.FAILED
    # An option sits beside the kind, as the API takes it (it refuses an ``options`` field).
    assert run("estimate", "database", "--option", "engine=postgres") == 0
    assert body(priced.calls.last.request) == {"items": [{"kind": "database", "engine": "postgres"}]}


# --- docs, skill, help, mcp -------------------------------------------------------


def test_docs_and_skills_print_markdown_with_no_key(home, api, monkeypatch, capsys):
    monkeypatch.delenv("NOCLICK_API_KEY")
    api.get("/v1/docs/apps").respond(json={"object": "doc", "id": "guide:apps", "kind": "guide", "title": "Apps",
                                           "summary": "", "url": None, "status": "built",
                                           "text": "Deploy an app.", "sections": ["guide:apps#deploy"]})
    assert run("docs", "apps") == 0
    out = capsys.readouterr()
    assert out.out == "# Apps\n\nDeploy an app.\n" and "noclick docs guide:apps#deploy" in out.err
    listed = api.get("/v1/docs").respond(json=listing(
        {"id": "skill:ship-an-app", "kind": "skill", "title": "Ship an app", "snippet": "From code to live."}))
    assert run("skill") == 0 and listed.calls.last.request.url.params["kind"] == "skill"
    assert "skill:ship-an-app" in capsys.readouterr().out
    api.get("/v1/docs/skill:nope").respond(404, json={"error": {"type": "not_found", "message": "No doc."}})
    assert run("skill", "nope") == exits.FAILED
    assert "noclick docs skill:ship-an-app" in capsys.readouterr().err


def test_help_json_lists_these_commands_from_the_manifest(capsys):
    assert run("help", "--json") == 0
    commands = {" ".join(c["path"]): c for c in json.loads(capsys.readouterr().out)["commands"]}
    for name in ("setup", "init", "live start", "live end", "live push", "wait", "docs", "skill", "mcp"):
        assert name in commands and commands[name].get("examples"), name
    assert {"--grep", "--since", "--timeout", "--json"} <= {f["flag"] for f in commands["logs"]["flags"]}


def test_mcp_prints_or_installs_the_server_never_the_key(home, here, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_HOME", str(here / "codex"))
    assert run("mcp", "claude") == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["mcpServers"]["noclick"] == {"type": "http", "url": "https://mcp.noclick.com",
                                              "headers": {"Authorization": "Bearer ${NOCLICK_API_KEY}"}}
    assert not (here / ".mcp.json").exists()
    for harness, path in (("claude", here / ".mcp.json"), ("cursor", here / ".cursor" / "mcp.json"),
                          ("codex", here / "codex" / "config.toml")):
        assert run("mcp", harness, "--install") == 0
        written = path.read_text()
        assert "nk_live_test" not in written and "mcp.noclick.com" in written
        assert run("mcp", harness, "--install") == 0  # twice changes nothing
        assert path.read_text() == written
    assert 'bearer_token_env_var = "NOCLICK_API_KEY"' in (here / "codex" / "config.toml").read_text()
    assert "${env:NOCLICK_API_KEY}" in (here / ".cursor" / "mcp.json").read_text()
    assert run("mcp", "cursor", "--oauth", "--dir", str(here / "other")) == 0
    assert "headers" not in capsys.readouterr().out.split("mcpServers")[1]

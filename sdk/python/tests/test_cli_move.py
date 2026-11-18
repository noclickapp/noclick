"""``noclick agents move``: the CLI carries what a coding session chose to a NoClick agent with the move's own key,
kept in a file only its user reads and never printed. ``repo`` commits the uncommitted work with a temporary index
(the checkout, its index and stash untouched) and pushes it to the work branch with the URL kept out of argv."""

import io
import json
import os
import stat
import subprocess
import tarfile

import httpx
import pytest

from noclick import cli
from platform_helpers import BASE, body
from test_cli import home, run  # noqa: F401

VIEW = {"object": "agent_move", "id": "mv_1", "status": "moving", "workspace_id": None, "draft": {}, "source": None,
        "steps": [], "agent_id": None, "conversation": None, "error": None, "guide_url": "https://noclick.com/move.md",
        "expires_at": "2026-11-10T11:00:00Z", "created_at": "2026-11-10T10:00:00Z",
        "lands_as": {"name": "acme", "harness": "claude_code", "cwd": "/workspace/acme"},
        "arrived": {"session": None, "repo": None, "files": [], "env": [], "mcp_servers": [], "skills": [],
                    "memories": [], "note": None, "instructions": None}}


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def moving(home, api, monkeypatch):  # noqa: F811
    monkeypatch.delenv("NOCLICK_API_KEY")
    api.post("/v1/moves/redeem").respond(200, text="nk_live_movekey\n")
    assert run("agents", "move", "redeem", "--code", "nc_move_abc", "--host", "ana-mbp") == 0
    api.get("/v1/moves/current").respond(json=VIEW)
    return home


def test_redeem_keeps_the_key_private_and_never_prints_it(moving, api, capsys):
    saved = moving.config / cli.MOVE_KEY_FILE
    assert json.loads(saved.read_text()) == {"key": "nk_live_movekey", "api_url": BASE}
    assert stat.S_IMODE(os.stat(saved).st_mode) == 0o600
    out = capsys.readouterr()
    assert "nk_live_movekey" not in out.out + out.err
    calls = api.calls
    assert calls[0].request.content == b"code=nc_move_abc&host=ana-mbp"
    # Every later call signs in with the move's key alone.
    assert run("agents", "move", "status") == 0
    assert calls.last.request.headers["Authorization"] == "Bearer nk_live_movekey"
    assert "/workspace/acme" in capsys.readouterr().out


def test_the_session_files_go_up_as_a_tar_of_the_harness_home(moving, api, tmp_path, capsys):
    home_dir = tmp_path / ".claude"
    session = home_dir / "projects" / "-Users-ana-code-acme" / "s1.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text('{"type": "user"}\n')
    upload = api.put("/v1/moves/current/session").respond(json={**VIEW, "arrived": {**VIEW["arrived"], "session": {
        "messages": 3, "tool_calls": 1, "title": "Fix retries"}}})
    assert run("agents", "move", "session", "--harness", "claude_code", "--home", str(home_dir),
               "--cwd", "/Users/ana/code/acme", "--session-id", "s1", "projects/-Users-ana-code-acme/s1.jsonl") == 0
    request = upload.calls.last.request
    assert httpx.URL(str(request.url)).params["cwd"] == "/Users/ana/code/acme"
    with tarfile.open(fileobj=io.BytesIO(request.content), mode="r:gz") as archive:
        assert archive.getnames() == ["projects/-Users-ana-code-acme/s1.jsonl"]
    assert "Read 3 messages" in capsys.readouterr().out


def test_a_secret_needs_the_persons_yes_and_is_never_printed(moving, api, tmp_path, monkeypatch, capsys):
    consent = api.put("/v1/moves/current/consent").respond(json={**VIEW, "arrived": {**VIEW["arrived"], "consent": [
        {"name": "database-url", "kind": "database URL", "to": "env DATABASE_URL"}]}})
    assert run("agents", "move", "consent", "database-url:database URL:env DATABASE_URL", "--yes") == 0
    assert body(consent.calls.last.request) == {"secrets": [
        {"name": "database-url", "kind": "database URL", "to": "env DATABASE_URL"}], "confirmed": True}
    dotenv = tmp_path / ".env"
    dotenv.write_text('# keys\nDATABASE_URL="postgres://u:p4ss@db/x"\nexport STRIPE_KEY=sk_test_123\n')
    sent = api.put("/v1/moves/current/secrets/database-url").respond(json=VIEW)
    assert run("agents", "move", "secret", "database-url", "--from-dotenv", "DATABASE_URL", "--dotenv", str(dotenv),
               "--to-env", "DATABASE_URL") == 0
    assert body(sent.calls.last.request) == {"value": "postgres://u:p4ss@db/x", "to": {"env": "DATABASE_URL"}}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-moved")
    key = api.put("/v1/moves/current/secrets/anthropic").respond(json=VIEW)
    assert run("agents", "move", "secret", "anthropic", "--from-env", "ANTHROPIC_API_KEY", "--to-model",
               "anthropic") == 0
    assert body(key.calls.last.request) == {"value": "sk-ant-moved", "to": {"model": "anthropic"}}
    hosts = tmp_path / "hosts.yml"
    hosts.write_text("github.com:\n  oauth_token: gho_x\n")
    gh = api.put("/v1/moves/current/secrets/gh-hosts").respond(json=VIEW)
    assert run("agents", "move", "secret", "gh-hosts", "--from-file", str(hosts), "--to-file",
               "~/.config/gh/hosts.yml") == 0
    assert body(gh.calls.last.request) == {"value": "github.com:\n  oauth_token: gho_x\n",
                                           "to": {"file": "~/.config/gh/hosts.yml"}}
    out = capsys.readouterr()
    assert "p4ss" not in out.out + out.err and "sk-ant-moved" not in out.out + out.err and "gho_x" not in out.out
    assert run("agents", "move", "secret", "x", "--from-dotenv", "NOT_THERE", "--dotenv", str(dotenv)) == 1


def test_setup_checkout_and_the_plan_link(moving, api, capsys):
    setup = api.put("/v1/moves/current/setup").respond(json=VIEW)
    assert run("agents", "move", "setup", "npm install -g @linear/cli") == 0
    assert body(setup.calls.last.request) == {"commands": ["npm install -g @linear/cli"]}
    checkout = api.put("/v1/moves/current/checkout").respond(json=VIEW)
    assert run("agents", "move", "checkout", "--url", "https://github.com/acme/web.git", "--branch", "noclick/a",
               "--secret", "github-token") == 0
    assert body(checkout.calls.last.request) == {"url": "https://github.com/acme/web.git", "branch": "noclick/a",
                                                 "secret": "github-token"}
    api.post("/v1/moves/current/plan_link").respond(json={"object": "plan_link", "url": "https://x.test/sign-in",
                                                          "integration": "anthropic"})
    assert run("agents", "move", "plan-link") == 0
    assert "https://x.test/sign-in" in capsys.readouterr().out


def test_repo_pushes_uncommitted_work_without_touching_the_checkout(moving, api, tmp_path, monkeypatch, capsys):
    repo = tmp_path / "acme"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "ana@acme.test", cwd=repo)
    _git("config", "user.name", "Ana", cwd=repo)
    (repo / "app.py").write_text("print(1)\n")
    (repo / ".gitignore").write_text("node_modules/\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "first", cwd=repo)
    head = _git("rev-parse", "HEAD", cwd=repo)
    (repo / "app.py").write_text("print(2)\n")                      # changed, not committed
    (repo / "notes.md").write_text("todo\n")                         # untracked
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "big.js").write_text("ignored\n")       # ignored
    before = _git("status", "--porcelain", cwd=repo)

    api.post("/v1/moves/current/repo").respond(json={
        "object": "move_repo", "repo_id": "rp_1", "name": "acme", "branch": "laptop/ana-mbp-20261110", "path": "acme",
        "url": "https://x:secret-token@git.test/acme.git", "expires_at": "2026-11-10T10:10:00Z",
        "cwd": "/workspace/acme"})
    pushed = []

    def fake_git(*args, cwd=None, env=None):
        if args[0] == "push":
            pushed.append((args, env))
            return ""
        return real_git(*args, cwd=cwd, env=env)

    real_git = cli._git
    monkeypatch.setattr(cli, "_git", fake_git)
    assert run("agents", "move", "repo", "--path", str(repo), "--host", "ana-mbp") == 0
    [(args, env)] = pushed
    commit = args[2].split(":")[0].lstrip("+")
    assert args[2] == f"+{commit}:refs/heads/laptop/ana-mbp-20261110" and "secret-token" not in " ".join(args)
    assert env["GIT_CONFIG_VALUE_0"] == "https://x:secret-token@git.test/acme.git"
    # The work commit holds the change and the untracked file, not what's ignored, on top of HEAD.
    assert _git("rev-parse", f"{commit}^", cwd=repo) == head
    assert _git("show", f"{commit}:app.py", cwd=repo) == "print(2)"
    files = _git("ls-tree", "-r", "--name-only", commit, cwd=repo).splitlines()
    assert "notes.md" in files and not any(f.startswith("node_modules") for f in files)
    # The checkout, its index and HEAD are as they were.
    assert _git("rev-parse", "HEAD", cwd=repo) == head and _git("status", "--porcelain", cwd=repo) == before
    assert "secret-token" not in capsys.readouterr().out


def test_skill_memory_note_and_finish(moving, api, tmp_path, capsys):
    skill = tmp_path / "release-notes"
    (skill / "templates").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: release-notes\ndescription: Write release notes\n---\nSteps.\n")
    (skill / "templates" / "notes.md").write_text("# {{version}}\n")
    added = api.put("/v1/moves/current/skills/release-notes").respond(json=VIEW)
    assert run("agents", "move", "skill", str(skill)) == 0
    with tarfile.open(fileobj=io.BytesIO(added.calls.last.request.content), mode="r:gz") as archive:
        assert sorted(archive.getnames()) == ["SKILL.md", "templates/notes.md"]
    (tmp_path / "empty").mkdir()
    assert run("agents", "move", "skill", str(tmp_path / "empty")) == 1

    memory = api.put("/v1/moves/current/memories/deploy-steps").respond(json=VIEW)
    (tmp_path / "deploy.md").write_text("make ship\n")
    assert run("agents", "move", "memory", "deploy-steps", "--file", str(tmp_path / "deploy.md"),
               "--description", "How it deploys") == 0
    assert body(memory.calls.last.request) == {"content": "make ship\n", "description": "How it deploys"}
    note = api.put("/v1/moves/current/note").respond(json=VIEW)
    (tmp_path / "note.md").write_text("Next: the third retry.\n")
    assert run("agents", "move", "note", "--file", str(tmp_path / "note.md")) == 0
    assert note.calls.last.request.content == b"Next: the third retry.\n"

    asked = api.post("/v1/moves/current/finish").respond(json={**VIEW, "question": "No MCP server and no skill?"})
    # A finish that asks first keeps the move's key, for the finish that answers.
    assert run("agents", "move", "finish") == 0 and asked.call_count == 1
    assert "No MCP server and no skill?" in capsys.readouterr().out
    assert (moving.config / cli.MOVE_KEY_FILE).exists()
    finish = api.post("/v1/moves/current/finish").respond(json={**VIEW, "status": "done", "agent_id": "ag_1",
                                                                "conversation": "moved-s1"})
    # On a harness the carried key runs, when the session's own doesn't.
    assert run("agents", "move", "finish", "--harness", "opencode", "--model", "openrouter/anthropic/claude-sonnet-4.5",
               "--none", "mcp_servers", "--none", "skills") == 0
    assert body(finish.calls.last.request) == {"harness": "opencode", "model": "openrouter/anthropic/claude-sonnet-4.5",
                                               "none": ["mcp_servers", "skills"]}
    assert "agent ag_1, conversation moved-s1" in capsys.readouterr().out
    # The key's file goes with the move.
    assert not (moving.config / cli.MOVE_KEY_FILE).exists()
    assert run("agents", "move", "status") == 1

"""Shipping and configuring an app from a folder: deploy (a checkout with git, any other folder through the API),
link, status, releases, rollback, promote, delete, secrets, settings, bindings and domains."""

import io
import json
import subprocess

import httpx
import pytest

from noclick import cli
from noclick._cli import appconfig, link as links
from noclick._cli.parts import ship
from platform_helpers import BASE, body, listing, operation

PROJECT = {"object": "project", "id": "5c2e8a1f-3b7d-4e9a-a6c4-8d1f0e2b3a79", "name": "booking",
           "url": "https://booking.noclick.site", "repo_id": "repo_1", "production_branch": "main", "user_id": None,
           "region": "us-east", "runtime": "auto", "domain_names": []}
APP = PROJECT["id"]
GIT = ("git", "-c", "user.email=ana@acme.test", "-c", "user.name=Ana")


@pytest.fixture
def shell(monkeypatch, tmp_path, client):
    """A signed-in shell in a folder of its own, no git identity or config of its own beyond what a test sets."""
    monkeypatch.setenv("NOCLICK_API_KEY", "nk_live_test")
    monkeypatch.setenv("NOCLICK_API_URL", BASE)
    monkeypatch.setenv("NOCLICK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("NOCLICK_PROFILE", raising=False)
    work = tmp_path / "booking"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def run(*argv):
    return cli.main(list(argv))


def git(*args, cwd):
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def checkout(work, files):
    git("init", "-q", "-b", "main", cwd=work)
    for path, text in files.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(text)
    git("add", ".", cwd=work)
    git("commit", "-qm", "v1", cwd=work)
    return git("rev-parse", "HEAD", cwd=work)


def deployed(url="https://booking.noclick.site", **extra):
    return {"object": "deployment", "id": "dep_2", "project_id": APP, "branch": "main", "status": "ready",
            "url": url, "production": True, **extra}


def app_routes(api, remote, *, project=PROJECT):
    """The app's own reads, its repo's push URL (a bare repo on disk) and its deploy."""
    api.get("/v1/projects").respond(json=listing(project))
    api.get(f"/v1/projects/{APP}").respond(json=project)
    api.post("/v1/repos/repo_1/clone_url").respond(json={"url": remote.as_uri()})
    return api.post(f"/v1/projects/{APP}/deployments").respond(202, json=operation(
        "op_d", kind="project.deploy", status="succeeded", result=deployed()))


def link(work):
    links.write("booking", app_id=APP, api_url=BASE, root=work)


# --- a checkout ------------------------------------------------------------------------------------------------


def test_a_folders_first_deploy_makes_its_app_ships_its_commit_and_links_it(shell, api, tmp_path, capsys):
    head = checkout(shell, {"index.html": "<h1>Booking</h1>\n"})
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    api.get("/v1/projects").mock(side_effect=[httpx.Response(200, json=listing()),   # no app by the folder's name
                                              httpx.Response(200, json=listing())])
    api.get("/v1/repos").respond(json=listing())
    make_repo = api.post("/v1/repos").respond(201, json={"object": "repo", "id": "repo_1", "name": "booking"})
    make_app = api.post("/v1/projects").respond(201, json=PROJECT)
    api.post("/v1/repos/repo_1/clone_url").respond(json={"url": remote.as_uri()})
    deploy = api.post(f"/v1/projects/{APP}/deployments").respond(202, json=operation(
        "op_d", kind="project.deploy", status="succeeded", result=deployed()))

    assert run("deploy") == 0
    assert body(make_repo.calls.last.request)["name"] == "booking"
    assert body(make_app.calls.last.request)["name"] == "booking"
    assert git("rev-parse", "main", cwd=remote) == head  # the commit itself, no snapshot
    assert body(deploy.calls.last.request) == {"branch": "main", "commit": head}
    out = capsys.readouterr()
    assert out.out.splitlines()[-1] == "https://booking.noclick.site"
    assert "Made the app booking" in out.err and "a site of files" in out.err and "Ready: https://booking.noclick.site · production · release dep_2 · " in out.err
    assert "Push…\nPush: " in out.err
    saved = json.loads((shell / ".noclick" / "project.json").read_text())
    assert (saved["app"], saved["app_id"]) == ("booking", APP)
    assert git("status", "--porcelain", cwd=shell) == ""  # .noclick/ ignores itself: never committed or shipped


def test_an_unlinked_folder_never_deploys_over_an_app_it_isnt_tied_to(shell, api, capsys):
    checkout(shell, {"index.html": "<h1>Booking</h1>\n"})
    api.get("/v1/projects").respond(json=listing(PROJECT))
    assert run("deploy") == 1
    err = capsys.readouterr().err
    assert "already have an app named booking" in err and "noclick link booking" in err
    assert not (shell / ".noclick").exists()


def test_a_dirty_checkout_ships_a_snapshot_and_the_checkout_never_changes(shell, api, tmp_path, capsys):
    head = checkout(shell, {"app.js": "v1\n", ".gitignore": "secrets.txt\n"})
    link(shell)
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    deploy = app_routes(api, remote)
    (shell / "app.js").write_text("v2\n")
    (shell / "form.js").write_text("new\n")
    (shell / "secrets.txt").write_text("ignored, never shipped\n")
    git("add", "app.js", cwd=shell)  # staged, as the person left it
    before = git("status", "--porcelain", cwd=shell)

    assert run("deploy", "--json") == 0
    out = capsys.readouterr()
    result = json.loads(out.out)
    snapshot = git("rev-parse", "main", cwd=remote)
    assert result["snapshot"] and result["commit"] == snapshot and result["url"] == "https://booking.noclick.site"
    assert {(f["status"], f["path"]) for f in result["files"]} == {("M", "app.js"), ("A", "form.js")}
    assert git("rev-parse", f"{snapshot}^", cwd=remote) == head
    assert git("show", f"{snapshot}:app.js", cwd=remote) == "v2"
    assert git("show", f"{snapshot}:form.js", cwd=remote) == "new"
    assert "secrets.txt" not in git("ls-tree", "--name-only", snapshot, cwd=remote)
    assert body(deploy.calls.last.request) == {"branch": "main", "commit": snapshot}
    assert git("rev-parse", "HEAD", cwd=shell) == head and git("status", "--porcelain", cwd=shell) == before
    assert "M app.js" in out.err and "A form.js" in out.err

    # Committed now: the app's branch holds the snapshot, which this commit takes the place of (never a conflict).
    git("commit", "-qam", "v2", cwd=shell)
    git("add", "form.js", cwd=shell)
    git("commit", "-qm", "form", cwd=shell)
    assert run("deploy") == 0
    shipped = git("rev-parse", "main", cwd=remote)
    assert git("rev-parse", f"{shipped}^1", cwd=remote) == git("rev-parse", "HEAD", cwd=shell)
    assert git("rev-parse", f"{shipped}^2", cwd=remote) == snapshot
    assert git("rev-parse", f"{shipped}^{{tree}}", cwd=remote) == git("rev-parse", "HEAD^{tree}", cwd=shell)
    assert "takes the place of the earlier snapshot" in capsys.readouterr().err

    # Someone else's commit on the app's branch is never written over: fetched for merging instead.
    other = tmp_path / "other"
    git("clone", "-q", remote.as_uri(), str(other), cwd=tmp_path)
    (other / "sign_in.js").write_text("// an app service's\n")
    git("add", ".", cwd=other)
    git("commit", "-qm", "Add sign-in", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)
    (shell / "app.js").write_text("v3\n")
    calls = deploy.call_count
    assert run("deploy") == 1
    assert "git merge noclick/main" in capsys.readouterr().err
    assert deploy.call_count == calls
    assert git("log", "-1", "--format=%s", "noclick/main", cwd=shell) == "Add sign-in"


def test_a_secret_is_left_out_and_said_and_only_a_committed_one_refuses(shell, api, tmp_path, capsys):
    head = checkout(shell, {"app.js": "v1\n"})
    link(shell)
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    deploy = app_routes(api, remote)
    (shell / ".env").write_text("STRIPE_KEY=sk_live_abc\nexport DB_URL=postgres://u:p@h/db\n")
    # A checkout whose only change is a secret ships its commit as it is; --only-committed takes it as clean.
    assert run("deploy", "--only-committed") == 0
    assert body(deploy.calls.last.request) == {"branch": "main", "commit": head}
    capsys.readouterr()

    (shell / ".env.example").write_text("STRIPE_KEY=\n")
    assert run("deploy", "--json") == 0
    out = capsys.readouterr()
    result = json.loads(out.out)
    assert result["left_out"] == [{"path": ".env",
                                   "why": "looks like a secret, and a secret never ships in the app's code",
                                   "names": ["STRIPE_KEY", "DB_URL"],
                                   "next_steps": ["noclick secret set STRIPE_KEY --from-env STRIPE_KEY",
                                                  "noclick secret set DB_URL --from-env DB_URL"]}]
    shipped = git("rev-parse", "main", cwd=remote)
    assert git("ls-tree", "--name-only", shipped, cwd=remote).split() == [".env.example", "app.js"]
    assert git("rev-parse", f"{shipped}^", cwd=remote) == head  # a snapshot of what else changed, on the commit
    assert "noclick secret set DB_URL --from-env DB_URL" in out.err
    assert "sk_live" not in out.out + out.err and "u:p@h" not in out.out + out.err


    # Committed, it's in the app's history either way: refused before anything is pushed.
    git("add", "-f", ".env", cwd=shell)
    git("commit", "-qm", "oops", cwd=shell)
    calls = deploy.call_count
    assert run("deploy") == 1
    err = capsys.readouterr().err
    assert ".env looks like a secret and is committed in" in err and "git rm --cached .env" in err
    assert deploy.call_count == calls and git("rev-parse", "main", cwd=remote) == shipped
    git("reset", "-q", "--hard", head, cwd=shell)
    (shell / "app.js").write_text("v2\n")
    assert run("deploy", "--only-committed") == 1
    assert "uncommitted changes" in capsys.readouterr().err


def test_a_preview_deploy_ships_its_branch_and_says_how_to_promote_it(shell, api, tmp_path, capsys):
    checkout(shell, {"index.html": "<h1>Booking</h1>\n"})
    link(shell)
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    deploy = app_routes(api, remote)
    deploy.respond(202, json=operation("op_d", kind="project.deploy", status="succeeded", result=deployed(
        url="https://preview--booking.noclick.site", branch="preview", production=False)))
    assert run("deploy", "--preview") == 0
    assert body(deploy.calls.last.request)["branch"] == "preview"
    out = capsys.readouterr()
    assert out.out.strip() == "https://preview--booking.noclick.site" and "noclick promote preview" in out.err


def test_a_deploy_token_signs_every_call_and_leaves_noclick_json_to_the_deploys_check(shell, api, tmp_path,
                                                                                      monkeypatch, capsys):
    """An agent's shell: no key, no login, only the token NoClick's MCP server handed it with the command."""
    monkeypatch.delenv("NOCLICK_API_KEY")
    checkout(shell, {"index.html": "<h1>Booking</h1>\n", "noclick.json": '{"env": {"A": "1"}}'})
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    deploy = app_routes(api, remote)
    settings = api.get(f"/v1/projects/{APP}/settings")
    assert run("deploy", "--app", "booking", "--token", "nk_mcp_deploy") == 0
    assert deploy.calls.last.request.headers["authorization"] == "Bearer nk_mcp_deploy"
    assert settings.call_count == 0 and "the deploy checks those noclick.json names" in capsys.readouterr().err
    assert not (shell / ".noclick").exists()  # named, never linked


# --- a folder outside git ---------------------------------------------------------------------------------------


def test_a_folder_outside_git_ships_what_changed_through_the_api(shell, api, capsys):
    link(shell)
    (shell / "index.html").write_text("<h1>v2</h1>\n")
    (shell / "about.html").write_text("<p>Same</p>\n")
    (shell / "node_modules").mkdir()
    (shell / "node_modules" / "left.js").write_text("left out\n")
    (shell / "dist").mkdir()
    (shell / "dist" / "built.js").write_text("ignored\n")
    (shell / ".gitignore").write_text("/dist\n")
    (shell / ".dev.vars").write_text("API_TOKEN=tok_live_1\n")  # a secret: left out, never sent
    api.get("/v1/projects").respond(json=listing(PROJECT))
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    api.get("/v1/repos/repo_1").respond(json={"object": "repo", "id": "repo_1", "name": "booking"})
    api.get("/v1/repos/repo_1/branches").respond(json=listing({"name": "main", "head": "a" * 40}))
    api.get("/v1/repos/repo_1/files").respond(json=listing(
        {"path": "index.html", "type": "file", "sha": "0" * 40},
        {"path": "about.html", "type": "file", "sha": ship._blob_sha(b"<p>Same</p>\n")},
        {"path": "old.html", "type": "file", "sha": "1" * 40}))
    commit = api.post("/v1/repos/repo_1/commits").respond(201, json={"sha": "b" * 40, "message": "Deploy"})
    deploy = api.post(f"/v1/projects/{APP}/deployments").respond(202, json=operation(
        "op_d", kind="project.deploy", status="succeeded", result=deployed()))

    assert run("deploy", "--no-git") == 0
    sent = {f["path"]: f for f in body(commit.calls.last.request)["files"]}
    assert set(sent) == {"index.html", ".gitignore", "old.html"}  # only what changed; old.html deleted
    assert sent["old.html"] == {"path": "old.html", "delete": True}
    assert body(commit.calls.last.request)["branch"] == "main"
    assert body(deploy.calls.last.request) == {"branch": "main", "commit": "b" * 40}
    err = capsys.readouterr().err
    assert "A index.html" not in err and "M index.html" in err and "D old.html" in err
    assert "Left out .dev.vars" in err and "noclick secret set API_TOKEN --from-env API_TOKEN" in err
    assert "tok_live" not in err

    # A link out of the folder would carry this machine's file: refused before anything is sent.
    (shell.parent / "id_ed25519").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    (shell / "key.txt").symlink_to(shell.parent / "id_ed25519")
    assert run("deploy", "--no-git") == 1
    assert "a link, key.txt" in capsys.readouterr().err and commit.call_count == 1


def test_a_site_of_files_holding_server_code_is_refused(shell, api, capsys):
    link(shell)
    (shell / "index.html").write_text("<h1>Hi</h1>\n")
    (shell / "app.py").write_text("SECRET = 'x'\n")
    commit = api.post("/v1/repos/repo_1/commits")
    assert run("deploy", "--no-git") == 1
    err = capsys.readouterr().err
    assert "app.py" in err and "--dir public" in err and commit.call_count == 0


# --- noclick.json and a wrangler config -------------------------------------------------------------------------

WRANGLER = """{
  // A Worker made for Cloudflare.
  "name": "booking",
  "main": "src/index.ts",
  "vars": {"API_BASE": "https://api.acme.test", "RETRIES": 3},
  "d1_databases": [{"binding": "DB", "database_name": "booking-db", "database_id": "x"}],
  "kv_namespaces": [{"binding": "CACHE", "id": "abc"}],
  "triggers": {"crons": ["0 * * * *"]},
}
"""


def test_a_wrangler_config_is_translated_into_noclick_json_then_given_to_the_app(shell, api, capsys):
    link(shell)
    (shell / "src").mkdir()
    (shell / "src" / "index.ts").write_text("export default { fetch() { return new Response('ok') } }\n")
    (shell / "wrangler.jsonc").write_text(WRANGLER)
    commit = api.post("/v1/repos/repo_1/commits")
    assert run("deploy", "--no-git") == 1
    written = json.loads((shell / "noclick.json").read_text())
    assert written == {"bindings": {"DB": {"database": "booking-db"}, "CACHE": {"dict": "booking-cache"}},
                       "env": {"API_BASE": "https://api.acme.test", "RETRIES": "3"},
                       "crons": [{"cron": "0 * * * *", "path": "/__scheduled"}]}
    err = capsys.readouterr().err
    assert "noclick.json now has it" in err and "bindings.DB → database booking-db (from d1_databases)" in err
    assert "still names d1_databases, kv_namespaces, triggers" in err and 'Project.current().database("DB")' in err
    assert commit.call_count == 0  # refused before anything was made or shipped

    # With what NoClick's build refuses gone from the wrangler config, the deploy gives the app the rest first.
    (shell / "wrangler.jsonc").write_text(WRANGLER.replace(
        '  "d1_databases": [{"binding": "DB", "database_name": "booking-db", "database_id": "x"}],\n', "").replace(
        '  "kv_namespaces": [{"binding": "CACHE", "id": "abc"}],\n', "").replace(
        '  "triggers": {"crons": ["0 * * * *"]},\n', ""))
    api.get("/v1/projects").respond(json=listing(PROJECT))
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    api.get(f"/v1/projects/{APP}/bindings").respond(json=listing())
    api.get("/v1/databases").respond(json=listing())
    made = api.post("/v1/databases").respond(201, json={"object": "database", "id": "db_1", "name": "booking-db"})
    api.get("/v1/dicts").respond(json=listing({"object": "dict", "id": "dc_1", "name": "booking-cache"}))
    bound = api.post(f"/v1/projects/{APP}/bindings").respond(201, json={"name": "DB", "kind": "database"})
    api.get(f"/v1/projects/{APP}/settings").respond(json=listing(
        {"name": "API_BASE", "value": "https://api.acme.test"}))
    put = api.put(f"/v1/projects/{APP}/settings/RETRIES").respond(json={"name": "RETRIES", "value": "3"})
    api.get(f"/v1/projects/{APP}/schedules").respond(json=listing())
    scheduled = api.post(f"/v1/projects/{APP}/schedules").respond(201, json={"id": "sch_1"})
    api.get("/v1/repos/repo_1/branches").respond(json=listing())
    commit.respond(201, json={"sha": "c" * 40})
    api.post(f"/v1/projects/{APP}/deployments").respond(202, json=operation(
        "op_d", kind="project.deploy", status="succeeded", result=deployed()))
    assert run("deploy", "--no-git") == 0
    assert body(made.calls.last.request) == {"name": "booking-db", "engine": "sqlite", "region": "us-east"}
    assert [body(c.request) for c in bound.calls] == [{"name": "DB", "kind": "database", "id": "db_1"},
                                                       {"name": "CACHE", "kind": "dict", "id": "dc_1"}]
    assert made.call_count == 1  # the dict was there already: bound as it is
    assert body(put.calls.last.request) == {"value": "3"}  # API_BASE already held it
    assert body(scheduled.calls.last.request) == {"cron": "0 * * * *", "tz": "UTC", "path": "/__scheduled"}
    err = capsys.readouterr().err
    assert "bound DB to the database booking-db" in err and "set RETRIES = 3" in err
    assert "added the schedule 0 * * * * (UTC) → POST /__scheduled" in err


def test_noclick_json_in_the_wrong_shape_is_refused_naming_the_fix(shell, capsys):
    link(shell)
    (shell / "noclick.json").write_text(json.dumps({"bindings": {"DB": {"database": "a", "bucket": "b"}}}))
    assert run("deploy", "--no-git") == 1
    assert "bindings.DB names database and bucket" in capsys.readouterr().err
    with pytest.raises(appconfig.ConfigError, match="crons\\[0\\].path"):
        appconfig.parse({"crons": [{"cron": "0 * * * *", "path": "jobs"}]})


# --- the app's commands -----------------------------------------------------------------------------------------


def test_commands_act_on_the_linked_app_and_say_how_to_link_one(shell, api, capsys):
    assert run("status") == 2  # a usage matter: which app
    assert "noclick link <app>" in capsys.readouterr().err
    api.get("/v1/projects").respond(json=listing(PROJECT))
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    assert run("link", "booking") == 0
    assert capsys.readouterr().out.strip() == "https://booking.noclick.site"
    assert run("open", "--no-browser") == 0
    assert capsys.readouterr().out.strip() == "https://booking.noclick.site"
    assert run("unlink") == 0 and not (shell / ".noclick").exists()


def test_status_says_everything_on_one_screen_and_a_read_it_cant_make_never_fails_it(shell, api, capsys):
    link(shell)
    live = {**deployed(), "id": "dep_2", "commit": "d" * 40}
    api.get(f"/v1/projects/{APP}").respond(json={**PROJECT, "production": live, "domain_names": ["book.acme.test"]})
    api.get(f"/v1/projects/{APP}/deployments").respond(json=listing(
        live, {**deployed(), "id": "dep_3", "branch": "new-form", "production": False,
               "url": "https://new-form--booking.noclick.site"}))
    api.get(f"/v1/projects/{APP}/bindings").respond(json=listing(
        {"name": "DB", "kind": "database", "resource_name": "booking-db"}))
    api.get(f"/v1/projects/{APP}/secrets").respond(json=listing({"name": "STRIPE_KEY"}))
    api.get(f"/v1/projects/{APP}/settings").respond(json=listing({"name": "API_BASE", "value": "x"}))
    api.get(f"/v1/projects/{APP}/usage").respond(403, json={"error": {"type": "permission_denied",
                                                                      "message": "This key can't read usage."}})
    api.get(f"/v1/projects/{APP}/logs").respond(json=listing({"at": "2026-11-25T10:00:00Z", "level": "error",
                                                              "message": "POST /book 500"}))
    api.get("/v1/deployments/dep_2/requests").respond(json={"requests": 120, "errors": 2, "error_rate": 0.0167,
                                                             "by_status": {}, "slowest_routes": []})
    assert run("status") == 0
    out = capsys.readouterr().out
    for said in ("booking  https://booking.noclick.site", "book.acme.test", "120 requests in the last hour, 2 errors",
                 "new-form: https://new-form--booking.noclick.site", "POST /book 500", "DB (database booking-db)",
                 "STRIPE_KEY", "API_BASE", "spend       unread (This key can't read usage.)"):
        assert said in out, said
    assert run("status", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["secrets"] == ["STRIPE_KEY"] and data["health"]["errors"] == 2 and "spend" not in data


def test_releases_rollback_and_promote(shell, api, capsys):
    link(shell)
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    live = {**deployed(), "id": "dep_2", "commit": "2" * 40}
    earlier = {**deployed(), "id": "dep_1", "commit": "1" * 40, "production": False}
    api.get(f"/v1/projects/{APP}/deployments").respond(json=listing(live, earlier))
    assert run("releases") == 0
    out = capsys.readouterr()
    assert "dep_2" in out.out and "noclick rollback <id>" in out.err
    back = api.post("/v1/deployments/dep_1/promote").respond(202, json=operation(
        "op_r", kind="deployment.promote", status="succeeded", result={**earlier, "production": True}))
    assert run("rollback") == 0  # the release before the live one
    assert back.call_count == 1 and capsys.readouterr().out.strip() == "https://booking.noclick.site"

    preview = {**deployed(), "id": "dep_3", "branch": "new-form", "production": False, "commit": "3" * 40}
    api.get(f"/v1/projects/{APP}/deployments").respond(json=listing(live, preview))
    promote = api.post("/v1/deployments/dep_3/promote").respond(202, json=operation(
        "op_p", kind="deployment.promote", status="succeeded",
        result={**preview, "production": True, "warning": "It's live, but / answered 500."}))
    assert run("promote", "new-form") == 1  # live, but not working
    assert promote.call_count == 1 and "answered 500" in capsys.readouterr().err


def test_delete_says_what_goes_and_deletes_only_with_yes(shell, api, capsys):
    link(shell)
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    preview = api.post("/v1/delete_previews").respond(201, json={
        "object": "delete_preview", "impact": {
            "deletes": "Moves booking to the trash: it goes offline at once.",
            "depends_on_it": ["It stops being served at book.acme.test."], "data_lost": [], "stops_billing": [],
            "reversible": True, "undo": "Restorable from the trash for 30 days."}, "confirm_token": "nk_cfm_x"})
    gone = api.delete(f"/v1/projects/{APP}").respond(json={
        "trash": {"id": "tr_1", "kind": "project", "resource_id": APP, "name": "booking"}, "operation_id": "op_x"})
    assert run("delete") == 2
    out = capsys.readouterr()
    assert gone.call_count == 0 and "book.acme.test" in out.err
    assert out.out.strip() == "noclick delete --app booking --yes"
    assert body(preview.calls.last.request) == {"method": "DELETE", "path": f"/v1/projects/{APP}"}
    assert run("delete", "--yes", "--delete-data") == 0
    assert gone.calls.last.request.url.params["delete_data"] == "true"
    assert not (shell / ".noclick").exists()


def test_a_secrets_value_is_never_echoed_nor_read_from_a_terminal(shell, api, monkeypatch, capsys):
    link(shell)
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    put = api.put(f"/v1/projects/{APP}/secrets/STRIPE_KEY").respond(json={})
    monkeypatch.setenv("STRIPE_LIVE", "sk_live_51abc")
    assert run("secret", "set", "STRIPE_KEY", "--from-env", "STRIPE_LIVE", "--env", "production") == 0
    assert body(put.calls.last.request) == {"value": "sk_live_51abc", "environment": "production"}
    monkeypatch.setattr("sys.stdin", io.StringIO("sk_test_42\n"))
    assert run("secret", "set", "STRIPE_KEY", "--stdin") == 0
    assert body(put.calls.last.request) == {"value": "sk_test_42"}
    out = capsys.readouterr()
    assert "sk_live" not in out.out + out.err and "sk_test" not in out.out + out.err

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", Terminal())
    assert run("secret", "set", "STRIPE_KEY", "--stdin") == 1
    assert "Pipe it" in capsys.readouterr().err and put.call_count == 2
    with pytest.raises(SystemExit):
        run("secret", "set", "STRIPE_KEY", "sk_live_on_argv")  # never a value on the command line


def test_env_and_bind_keep_noclick_json_in_step(shell, api, capsys):
    link(shell)
    (shell / "noclick.json").write_text(json.dumps({"env": {"A": "1"}, "bindings": {}}))
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    api.put(f"/v1/projects/{APP}/settings/PUBLIC_URL").respond(json={})
    assert run("env", "set", "PUBLIC_URL=https://book.acme.test") == 0
    api.get("/v1/buckets").respond(json=listing())
    made = api.post("/v1/buckets").respond(201, json={"object": "bucket", "id": "bk_1", "name": "uploads"})
    api.post(f"/v1/projects/{APP}/bindings").respond(201, json={"name": "UPLOADS", "kind": "bucket"})
    assert run("bind", "bucket", "uploads", "--public") == 0
    assert body(made.calls.last.request)["public"] is True
    assert capsys.readouterr().out.splitlines()[-1] == "UPLOADS"
    assert json.loads((shell / "noclick.json").read_text()) == {
        "env": {"A": "1", "PUBLIC_URL": "https://book.acme.test"},
        "bindings": {"UPLOADS": {"bucket": "uploads", "public": True}}}


def test_bind_objects_declares_the_class_in_the_wrangler_config_keeping_its_comments(shell, capsys):
    link(shell)
    (shell / "wrangler.jsonc").write_text('{\n  // the worker\n  "main": "src/index.ts", // its entry\n}\n')
    assert run("bind", "objects", "ChatRoom") == 0
    text = (shell / "wrangler.jsonc").read_text()
    assert "// the worker" in text and "// its entry" in text
    data = json.loads(appconfig.strip_jsonc(text))
    assert data["durable_objects"] == {"bindings": [{"name": "CHAT_ROOM", "class_name": "ChatRoom"}]}
    assert data["migrations"] == [{"tag": "v1", "new_sqlite_classes": ["ChatRoom"]}]
    assert run("bind", "objects", "Lobby", "--as", "LOBBY") == 0
    data = json.loads(appconfig.strip_jsonc((shell / "wrangler.jsonc").read_text()))
    assert [b["name"] for b in data["durable_objects"]["bindings"]] == ["CHAT_ROOM", "LOBBY"]
    assert data["migrations"][-1] == {"tag": "v2", "new_sqlite_classes": ["Lobby"]}
    assert "export class Lobby" in capsys.readouterr().err.replace("Export class", "export class")


def test_domain_add_prints_the_records_to_set(shell, api, capsys):
    link(shell)
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    api.post(f"/v1/projects/{APP}/domains").respond(201, json={
        "object": "domain", "id": "dom_1", "name": "book.acme.test", "status": "pending_dns",
        "records": [{"type": "CNAME", "name": "book", "value": "booking.noclick.site", "status": "pending"}]})
    assert run("domains", "add", "book.acme.test") == 0
    out = capsys.readouterr()
    assert "CNAME  book  booking.noclick.site" in out.out + out.err
    assert out.out.splitlines()[-1] == "https://book.acme.test"


def test_waiting_on_a_person_and_refusals_have_exit_codes_of_their_own(shell, api, capsys):
    link(shell)
    api.get(f"/v1/projects/{APP}").respond(json=PROJECT)
    api.put(f"/v1/projects/{APP}/settings/A").respond(402, json={"error": {
        "type": "approval_required", "message": "Your owner approves this first.",
        "approve_url": "https://noclick.com/approve/ap_1"}})
    assert run("env", "set", "A=1") == 3
    assert "open: https://noclick.com/approve/ap_1" in capsys.readouterr().err
    api.put(f"/v1/projects/{APP}/settings/A").respond(402, json={"error": {
        "type": "spend_cap_exceeded", "message": "The app's budget is used up."}})
    assert run("env", "set", "A=1") == 4


@pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True).returncode != 0, reason="needs git")
def test_a_push_to_a_git_endpoint_that_sends_nothing_gives_up_saying_so(tmp_path, monkeypatch):
    """Real git against a socket that takes the request and never answers: the push ends, never waits on."""
    import socket
    import threading
    import time

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    held = []
    threading.Thread(target=lambda: held.append(listener.accept()), daemon=True).start()
    work = tmp_path / "app"
    work.mkdir()
    head = checkout(work, {"a.txt": "a\n"})
    monkeypatch.setattr(cli, "GIT_GIVE_UP_S", 2)
    started = time.monotonic()
    try:
        with pytest.raises(cli.CommandError) as gave_up:
            ship._push(str(work), cli._repo_remote(f"http://t:secret@127.0.0.1:{listener.getsockname()[1]}/app.git"),
                       head, "main")
    finally:
        listener.close()
    assert time.monotonic() - started < 30
    assert gave_up.value.message == "The repo's git endpoint sent nothing for 2 seconds, so the push gave up."


def test_a_failed_build_shows_the_end_of_its_log_and_its_error_once(shell, api, tmp_path, capsys):
    checkout(shell, {"index.html": "<h1>Booking</h1>\n"})
    link(shell)
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    deploy = app_routes(api, remote)
    deploy.respond(202, json=operation("op_d", kind="project.deploy", status="failed", error={
        "type": "operation_failed", "message": "The build failed: no index.html.", "deployment_id": "dep_9"}))
    api.get("/v1/deployments/dep_9/logs").respond(json=listing(
        {"at": "2026-09-28T10:00:00Z", "level": "info", "message": "npm run build"},
        {"at": "2026-09-28T10:00:04Z", "level": "error", "message": "The build failed: no index.html."}))
    assert run("deploy") == 1
    err = capsys.readouterr().err
    assert "  npm run build" in err and err.count("The build failed: no index.html.") == 1


def test_a_same_size_edit_made_as_the_index_was_written_is_still_seen(shell):
    """git trusts a file's size and time only where they're older than its index's own time. The snapshot copies the
    index to add the folder to: a copy stamped now took an edit of the same size made in the index's second for
    unchanged, so --only-committed let it through and a snapshot left it out."""
    import os

    then = os.stat(shell).st_mtime_ns - 100 * 10**9
    git("init", "-q", "-b", "main", cwd=shell)
    git("config", "core.trustctime", "false", cwd=shell)  # a file's time and size alone decide, as on many systems
    app = shell / "app.js"
    app.write_text("v1\n")
    os.utime(app, ns=(then, then))  # older than the index, so git keeps its size as it is
    git("add", ".", cwd=shell)
    git("commit", "-qm", "v1", cwd=shell)
    app.write_text("v2\n")  # the same size...
    os.utime(app, ns=(then, then))  # ...and the same time
    os.utime(shell / ".git" / "index", ns=(then, then))  # written in that same instant: git checks its content
    assert ship.working_tree(str(shell)).changes == [("M", "app.js")]
    assert git("status", "--porcelain", cwd=shell) == "M app.js"  # as git itself sees it (this rewrites the index)


def test_a_deploy_draws_its_stages_and_build_lines_as_they_come_and_ctrl_c_leaves_it_running(shell, api, tmp_path,
                                                                                           capsys, monkeypatch):
    """Each read waits on the operation's own long-poll from the ``updated_at`` it last saw; piped, every stage and
    build line is a line of its own, then where it serves, its release and how long it took. Ctrl-C stops following
    and says how to pick it up again (exit 130); the deploy goes on."""
    link(shell)
    checkout(shell, {"index.html": "<h1>Booking</h1>\n"})
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    app_routes(api, remote).respond(202, json=operation("op_d", kind="project.deploy", status="queued",
                                                        updated_at="2026-11-28T10:00:00Z"))

    def moving(status, stage, lines, at, **extra):
        stages = [{"name": n, "status": "done" if i < stage else "current" if i == stage else "pending"}
                  for i, n in enumerate(["Queued", "Building", "Shipping", "Live"])]
        return httpx.Response(200, json=operation("op_d", kind="project.deploy", status=status, updated_at=at,
                                                  progress={"stages": stages, "lines": lines,
                                                            "line_count": len(lines)}, **extra))

    waits = api.get("/v1/operations/op_d/wait").mock(side_effect=[
        moving("running", 1, ["> vite build"], "2026-11-28T10:00:02Z"),
        moving("running", 2, ["> vite build", "built in 3.1s"], "2026-11-28T10:00:06Z"),
        moving("succeeded", 4, ["> vite build", "built in 3.1s", "==> / answered 200"], "2026-11-28T10:00:08Z",
               result=deployed()),
    ])
    assert run("deploy") == 0
    assert [c.request.url.params.get("changed_since") for c in waits.calls] == [
        "2026-11-28T10:00:00Z", "2026-11-28T10:00:02Z", "2026-11-28T10:00:06Z"]
    out = capsys.readouterr()
    assert out.out.splitlines()[-1] == "https://booking.noclick.site"
    drawn = out.err[out.err.index("Queue…"):]
    assert drawn.startswith("Queue…\nQueue: ") and "Build…\n  > vite build\n  built in 3.1s\nBuild: " in drawn
    assert "Release…\n  ==> / answered 200\nRelease: " in drawn
    assert "Ready: https://booking.noclick.site · production · release dep_2 · " in drawn

    def pressed_ctrl_c(coro):  # Ctrl-C reaches the main thread, where the read is waited on
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(ship, "run_sync", pressed_ctrl_c)
    assert run("deploy", "--json") == 130
    out = capsys.readouterr()
    assert json.loads(out.out)["operation_id"] == "op_d"  # --json still says what it started
    assert "Detached: it goes on. Follow it with: noclick wait op_d" in out.err

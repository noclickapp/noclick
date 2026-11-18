import base64

import httpx
import pytest

import noclick as nc
from platform_helpers import BASE, USER_ID, agent_row, body, listing, operation, trashed

REPO = {"object": "repo", "id": "repo_1", "name": "booking", "default_branch": "main", "size_bytes": 482133,
        "last_commit": {"sha": "9f2c1ab", "message": "Add the booking form", "author": "Ana Silva", "branch": "main",
                        "created_at": "2026-09-25T09:00:00Z", "files_changed": 3},
        "user_id": None, "created_at": "2026-09-20T10:00:00Z"}
DEPLOYMENT = {"object": "deployment", "id": "dep_1", "project_id": "prj_1", "branch": "main", "commit": "9f2c1ab",
              "commit_message": "Add the booking form", "status": "ready", "url": "https://booking.noclick.site",
              "production": True, "error": None, "created_at": "2026-09-25T09:01:00Z",
              "ready_at": "2026-09-25T09:02:10Z"}
PROJECT = {"object": "project", "id": "prj_1", "name": "booking", "url": "https://booking.noclick.site",
           "repo_id": "repo_1", "framework": "remix", "production_branch": "main",
           "domain_names": ["acmebooking.com"], "production": DEPLOYMENT, "user_id": None,
           "created_at": "2026-09-20T10:00:00Z"}
SCHEDULE = {"object": "schedule", "id": "sch_1", "project_id": "prj_1", "name": "/jobs/reminders",
            "cron": "0 9 * * 1-5", "tz": "America/New_York", "path": "/jobs/reminders", "status": "active",
            "paused_reason": None, "next_run": "2026-09-28T13:00:00Z", "last_run": None, "last_status": None,
            "created_at": "2026-09-25T10:00:00Z"}


# --- repos ------------------------------------------------------------------------

def test_repo_create_list_get_and_delete(api, client):
    create = api.post("/v1/repos").respond(json=REPO)
    listed = api.get("/v1/repos").respond(json=listing(REPO))
    api.get("/v1/repos/repo_1").respond(json=REPO)
    delete = api.delete("/v1/repos/repo_1").respond(json=trashed("repo", "repo_1", "booking"))

    with nc.as_user("user_42"):
        repo = nc.Repo.create("booking", default_branch="main")
    assert body(create.calls.last.request) == {"name": "booking", "default_branch": "main"}
    assert create.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (repo.name, repo.default_branch, repo.size_bytes) == ("booking", "main", 482133)
    assert isinstance(repo.last_commit, nc.Commit)
    assert (repo.last_commit.sha, repo.last_commit.files_changed) == ("9f2c1ab", 3)

    [first] = nc.Repo.list(user_filter=nc.ALL_USERS, limit=5)
    assert listed.calls.last.request.url.params["user_id"] == "all"
    assert "NoClick-User" not in listed.calls.last.request.headers
    assert first == nc.Repo.get("repo_1") and repr(first).startswith("Repo(id='repo_1'")
    item = first.delete()
    assert delete.call_count == 1
    assert (item.kind, item.resource_id, item.name, item.operation_id) == ("repo", "repo_1", "booking", "op_del")


def test_repo_from_name_is_lazy_and_creates_once(api, client):
    lookup = api.get("/v1/repos").mock(side_effect=[
        httpx.Response(200, json=listing()), httpx.Response(200, json=listing()),
    ])
    create = api.post("/v1/repos").mock(side_effect=[
        httpx.Response(200, json=REPO),
        httpx.Response(409, json={"error": {"type": "conflict", "message": "taken", "existing_id": "repo_1"}}),
    ])
    api.get("/v1/repos/repo_1").respond(json=REPO)

    repo = nc.Repo.from_name("booking", create_if_missing=True)
    assert lookup.call_count == 0
    assert repo.id == "repo_1"
    assert lookup.calls.last.request.url.params["name"] == "booking"
    assert body(create.calls.last.request) == {"name": "booking"}

    racing = nc.Repo.from_name("booking", create_if_missing=True, default_branch="trunk")
    assert racing.id == "repo_1"  # created concurrently: the existing one is adopted
    assert body(create.calls.last.request) == {"name": "booking", "default_branch": "trunk"}

    api.get("/v1/repos").respond(json=listing())
    with pytest.raises(nc.NotFound, match="No repo is named 'nope'"):
        nc.Repo.from_name("nope").hydrate()


def test_repo_clone_url_commit_read_and_files(api, client):
    clone = api.post("/v1/repos/repo_1/clone_url").respond(json={
        "url": "https://x-token:abc@git.noclick.app/booking.git", "expires_at": "2026-09-25T11:00:00Z"})
    commit = api.post("/v1/repos/repo_1/commits").respond(json={
        "sha": "a1b2c3d", "message": "Add the lookup route", "author": "noclick", "branch": "new-form",
        "created_at": "2026-09-25T10:00:00Z", "files_changed": 3})
    files = api.get("/v1/repos/repo_1/files")

    repo = nc.Repo.from_id("repo_1", user=USER_ID)
    assert repo.clone_url(write=True, ttl_s=600) == "https://x-token:abc@git.noclick.app/booking.git"
    assert body(clone.calls.last.request) == {"write": True, "ttl_s": 600}
    assert clone.calls.last.request.headers["NoClick-User"] == USER_ID
    repo.clone_url()
    assert body(clone.calls.last.request) == {"write": False}

    made = repo.commit({"src/index.ts": "export {};\n", "logo.png": b"\x89PNG", "old.txt": None},
                       message="Add the lookup route", branch="new-form")
    assert body(commit.calls.last.request) == {
        "message": "Add the lookup route", "branch": "new-form",
        "files": [
            {"path": "src/index.ts", "content": "export {};\n", "encoding": "utf-8"},
            {"path": "logo.png", "content": base64.b64encode(b"\x89PNG").decode(), "encoding": "base64"},
            {"path": "old.txt", "delete": True},
        ],
    }
    assert isinstance(made, nc.Commit) and (made.sha, made.branch) == ("a1b2c3d", "new-form")

    # A file NoClick can reach goes by reference: one of the account's files, a URL, a bucket's file.
    page = nc.Attachment("game.html", "https://assets.noclick.test/game.html", "text/html", id="att_1")
    repo.commit({"index.html": page, "logo.png": {"url": "https://example.com/logo.png"},
                 "fonts/a.woff2": {"bucket_id": nc.Bucket.from_id("bkt_1"), "key": "fonts/a.woff2"},
                 "notes.txt": {"attachment_id": "att_2"}}, message="Publish the game")
    assert body(commit.calls.last.request)["files"] == [
        {"path": "index.html", "attachment_id": "att_1"},
        {"path": "logo.png", "url": "https://example.com/logo.png"},
        {"path": "fonts/a.woff2", "bucket_id": "bkt_1", "key": "fonts/a.woff2"},
        {"path": "notes.txt", "attachment_id": "att_2"},
    ]
    shown = nc.Attachment("game.html", "https://assets.noclick.test/game.html", "text/html")
    with pytest.raises(ValueError, match="no id to commit by"):
        repo.commit({"index.html": shown}, message="Publish")

    files.mock(side_effect=[
        httpx.Response(200, content=b'{"name": "booking"}', headers={"content-type": "application/octet-stream"}),
        httpx.Response(200, json=listing({"path": "app/routes", "type": "dir", "size": None},
                                         {"path": "app/root.tsx", "type": "file", "size": 812})),
    ])
    assert repo.read("package.json", ref="main") == b'{"name": "booking"}'
    params = files.calls.last.request.url.params
    assert (params["path"], params["ref"]) == ("package.json", "main")
    assert files.calls.last.request.headers["Accept"] == "*/*"

    tree = repo.files("app/", recursive=True)
    params = files.calls.last.request.url.params
    assert (params["prefix"], params["recursive"], "ref" in params) == ("app/", "true", False)
    assert [(f.type, f.path, f.size) for f in tree] == [("dir", "app/routes", None), ("file", "app/root.tsx", 812)]
    assert all(isinstance(f, nc.RepoFile) for f in tree)


def test_repo_branches_and_commits(api, client):
    api.get("/v1/repos/repo_1/branches").respond(json=listing(
        {"name": "main", "head": "9f2c1ab", "updated_at": "2026-09-25T09:00:00Z"},
        {"name": "new-form", "head": "a1b2c3d", "updated_at": "2026-09-25T10:00:00Z"}))
    commits = api.get("/v1/repos/repo_1/commits").respond(json=listing(REPO["last_commit"], next_cursor="c2"))

    repo = nc.Repo.from_id("repo_1")
    branches = repo.branches()
    assert [(b.name, b.head) for b in branches] == [("main", "9f2c1ab"), ("new-form", "a1b2c3d")]
    assert isinstance(branches[0], nc.Branch) and branches[0].updated_at.hour == 9

    [latest] = repo.commits(branch="main", limit=1)
    params = commits.calls.last.request.url.params
    assert (params["branch"], params["limit"]) == ("main", "1")
    assert (latest.message, latest.author, latest.created_at.day) == ("Add the booking form", "Ana Silva", 25)

    page = repo.commits_page(branch="main", limit=50)
    assert (page.next_cursor, page.data[0].sha) == ("c2", latest.sha) and isinstance(page.data[0], nc.Commit)
    repo.commits_page(branch="main", limit=50, cursor=page.next_cursor)
    params = commits.calls.last.request.url.params
    assert (params["cursor"], params["limit"]) == ("c2", "50")


def test_repo_backups_list_and_restore(api, client):
    backup = {"object": "repo_backup", "id": "bak_1", "branch": "agent/new-form", "sha": "a1b2c3d",
              "reason": "rewritten", "agent_id": "agt_1", "created_at": "2026-10-16T09:00:00Z",
              "expires_at": "2026-11-15T09:00:00Z"}
    listed = api.get("/v1/repos/repo_1/backups").respond(json=listing(backup))
    restore = api.post("/v1/repos/repo_1/backups/bak_1/restore").respond(status_code=201, json={
        "object": "branch", "name": "agent/new-form-restored-20261016T100000Z", "head": "a1b2c3d",
        "updated_at": "2026-10-16T09:00:00Z", "restored_from": "bak_1"})

    repo = nc.Repo.from_id("repo_1")
    [kept] = repo.backups(branch="agent/new-form")
    assert listed.calls.last.request.url.params["branch"] == "agent/new-form"
    assert isinstance(kept, nc.RepoBackup)
    assert (kept.branch, kept.sha, kept.reason, kept.agent_id, kept.expires_at.month) == (
        "agent/new-form", "a1b2c3d", "rewritten", "agt_1", 11)
    branch = repo.restore_backup(kept)
    assert isinstance(branch, nc.Branch) and (branch.name, branch.head) == (
        "agent/new-form-restored-20261016T100000Z", "a1b2c3d")
    assert repo.restore_backup("bak_1").head == "a1b2c3d" and restore.call_count == 2


def test_repo_diff_reads_what_a_commit_changed(api, client):
    patch = "diff --git a/app/form.tsx b/app/form.tsx\n--- a/app/form.tsx\n+++ b/app/form.tsx\n@@ -1 +1 @@\n-a\n+b\n"
    api.get("/v1/repos/repo_1/commits/9f2c1ab").respond(json={
        **REPO["last_commit"], "parents": ["1a2b3c4"], "additions": 1, "deletions": 1, "files_changed": 2,
        "files": [
            {"object": "commit_file", "path": "app/form.tsx", "old_path": None, "status": "modified",
             "additions": 1, "deletions": 1, "size": 812, "patch": patch},
            {"object": "commit_file", "path": "public/logo.png", "old_path": None, "status": "added",
             "additions": None, "deletions": None, "size": 20480, "patch": None},
        ]})

    changes = nc.Repo.from_id("repo_1").diff("9f2c1ab")
    assert isinstance(changes, nc.CommitDiff) and isinstance(changes.files[0], nc.FileChange)
    assert (changes.commit.message, changes.parents, changes.additions, changes.deletions) == (
        "Add the booking form", ["1a2b3c4"], 1, 1)
    form, logo = changes.files
    assert (form.status, form.patch, form.size) == ("modified", patch, 812)
    assert (logo.path, logo.patch, logo.additions) == ("public/logo.png", None, None)


def test_repo_create_from_url_returns_the_import_whose_wait_gives_the_copied_repo(api, client):
    create = api.post("/v1/repos").mock(side_effect=[
        httpx.Response(201, json={**REPO, "name": "blog", "last_commit": None,
                                  "operation": operation(op_id="op_i", kind="repo.import", status="queued",
                                                         repo_id="repo_1")}),
        httpx.Response(201, json={**REPO, "operation": operation(op_id="op_j", kind="repo.import", status="queued",
                                                                 repo_id="repo_2")}),
    ])
    api.get("/v1/operations/op_i/wait").respond(json=operation(
        op_id="op_i", kind="repo.import", status="succeeded", repo_id="repo_1",
        result={"object": "repo_import", "repo": {**REPO, "name": "blog", "default_branch": "trunk"},
                "default_branch": "trunk", "head": REPO["last_commit"], "branches": 2, "tags": 3,
                "size_bytes": 48213}))
    api.get("/v1/operations/op_j/wait").respond(json=operation(
        op_id="op_j", kind="repo.import", status="failed", repo_id="repo_2",
        error={"type": "invalid_request", "message": "https://example.com/acme/private asked for a sign-in.",
               "next_step": "Make the repository public.", "field": "source.url"}))

    copy = nc.Repo.create("blog", from_url="https://github.com/acme/blog")
    assert body(create.calls.last.request) == {"name": "blog", "source": {"url": "https://github.com/acme/blog"}}
    assert isinstance(copy, nc.RepoImport) and isinstance(copy, nc.Operation)
    assert (copy.id, copy.repo_id, copy.repo._known("id")) == ("op_i", "repo_1", "repo_1")
    repo = copy.wait()
    assert isinstance(repo, nc.Repo) and (repo.id, repo.name, repo.default_branch) == ("repo_1", "blog", "trunk")

    with pytest.raises(nc.InvalidRequest) as refused:
        nc.Repo.create("v2", from_url="https://example.com/acme/private", ref="v2.0.0", default_branch="main").wait()
    assert body(create.calls.last.request) == {
        "name": "v2", "default_branch": "main", "source": {"url": "https://example.com/acme/private", "ref": "v2.0.0"}}
    assert refused.value.details["field"] == "source.url"

    with pytest.raises(ValueError):
        nc.Repo.create("blog", from_url="https://github.com/acme/blog", allow_existing=True)
    with pytest.raises(ValueError):
        nc.Repo.create("blog", ref="main")
    assert create.call_count == 2


def test_repo_export_and_export_to_github(api, client):
    export = api.post("/v1/repos/repo_1/export").mock(side_effect=[
        httpx.Response(202, json=operation(op_id="op_e", kind="repo.export", status="running")),
        httpx.Response(202, json=operation(op_id="op_g", kind="repo.export_to_github", status="running")),
        httpx.Response(424, json={"error": {"type": "needs_connection", "message": "Connect GitHub.",
                                            "connect_url": "https://noclick.com/c/abc"}}),
    ])
    api.get("/v1/operations/op_e/wait").respond(json=operation(
        op_id="op_e", kind="repo.export", status="succeeded",
        result={"url": "https://exports.noclick.app/e.zip", "expires_at": "2026-09-26T10:00:00Z",
                "contents": [{"kind": "code", "name": "agent-tools", "detail": "A git bundle."}]}))
    api.get("/v1/operations/op_g/wait").respond(json=operation(
        op_id="op_g", kind="repo.export_to_github", status="succeeded",
        result={"url": "https://github.com/acme/agent-tools"}))

    repo = nc.Repo.from_id("repo_1")
    bundle = repo.export().wait()
    assert body(export.calls.last.request) == {}
    assert isinstance(bundle, nc.ExportBundle) and bundle.contents[0].kind == "code"
    assert bundle.size_bytes == 0 and bundle.remaining_dependencies == []

    assert repo.export_to_github(connection="github", owner="acme").wait() == "https://github.com/acme/agent-tools"
    assert body(export.calls.last.request) == {"to": "github", "connection": "github", "owner": "acme",
                                               "private": True}
    with pytest.raises(nc.NeedsConnection) as needed:
        repo.export_to_github(connection=nc.Connection.from_id("conn_9"), owner="acme", name="tools", private=False)
    assert needed.value.connect_url == "https://noclick.com/c/abc"
    assert body(export.calls.last.request) == {"to": "github", "connection": "conn_9", "owner": "acme",
                                               "name": "tools", "private": False}


# --- projects ---------------------------------------------------------------------

def test_project_from_name_creates_its_repo_first_and_converges(api, client):
    api.get("/v1/repos").respond(json=listing())
    make_repo = api.post("/v1/repos").respond(json=REPO)
    lookup = api.get("/v1/projects").mock(side_effect=[
        httpx.Response(200, json=listing()),
        httpx.Response(200, json=listing({**PROJECT, "framework": "vite"})),
    ])
    create = api.post("/v1/projects").respond(json=PROJECT)
    patch = api.patch("/v1/projects/prj_1").respond(json=PROJECT)

    repo = nc.Repo.from_name("booking", create_if_missing=True)
    app = nc.Project.from_name("booking", repo=repo, create_if_missing=True)
    assert make_repo.call_count == 0 and lookup.call_count == 0  # lazy
    assert app.url == "https://booking.noclick.site"
    assert make_repo.call_count == 1
    assert body(create.calls.last.request) == {"name": "booking", "repo_id": "repo_1"}
    assert lookup.calls[0].request.url.params["name"] == "booking"

    defined = nc.Project.from_name("booking", repo="repo_1", framework="remix", create_if_missing=True)
    assert defined.framework == "remix"
    assert body(patch.calls.last.request) == {"framework": "remix"}  # only what differs

    production = app.production
    assert isinstance(production, nc.Deployment) and production.status == "ready" and production.production
    assert app.domain_names == ["acmebooking.com"]
    assert isinstance(app.repo, nc.Repo) and app.repo._known("id") == "repo_1"
    assert isinstance(app.secrets, nc.ProjectSecrets)
    assert isinstance(app.email, nc.ProjectEmail) and isinstance(app.payments, nc.ProjectPayments)
    assert isinstance(app.sign_in, nc.ProjectSignIn)


def test_project_create_list_get(api, client):
    create = api.post("/v1/projects").respond(json={**PROJECT, "user_id": USER_ID})
    listed = api.get("/v1/projects").respond(json=listing(PROJECT, {**PROJECT, "id": "prj_2", "production": None}))
    api.get("/v1/projects/prj_2").respond(json={**PROJECT, "id": "prj_2", "production": None})

    with nc.as_user("acme"):
        app = nc.Project.create("status-page", framework="astro")
    assert body(create.calls.last.request) == {"name": "status-page", "framework": "astro"}  # a new repo is made for it
    assert create.calls.last.request.headers["NoClick-User"] == "acme"
    assert app.user_id == USER_ID

    apps = nc.Project.list(user_filter=nc.ALL_USERS)
    assert listed.calls.last.request.url.params["user_id"] == "all"
    assert [a.id for a in apps] == ["prj_1", "prj_2"] and apps[1].production is None
    assert nc.Project.get("prj_2").production is None


def test_an_app_names_its_runtime_and_its_own_hostname(api, client):
    edge = {**PROJECT, "hostname": "booking.noclick.site", "runtime": "edge",
            "production": {**DEPLOYMENT, "environment": "production"}}
    create = api.post("/v1/projects").respond(json=edge)
    app = nc.Project.create("booking", runtime="edge", region="eu")
    assert body(create.calls.last.request) == {"name": "booking", "runtime": "edge", "region": "eu"}
    assert (app.hostname, app.runtime, app.production.environment) == ("booking.noclick.site", "edge", "production")
    api.get("/v1/projects").respond(json=listing())
    nc.Project.from_name("flask-app", runtime="container", create_if_missing=True).hydrate()
    assert body(create.calls.last.request) == {"name": "flask-app", "runtime": "container"}


def test_an_app_opts_into_auto_and_a_deployment_says_where_it_ran_and_why(api, client):
    lookup = api.get("/v1/projects").respond(json=listing({**PROJECT, "runtime": "edge"}))
    patch = api.patch("/v1/projects/prj_1").mock(
        side_effect=lambda request: httpx.Response(200, json={**PROJECT, **body(request)}))
    defined = nc.Project.from_name("booking", runtime="auto", create_if_missing=True)
    assert defined.runtime == "auto" and lookup.call_count == 1
    assert body(patch.calls.last.request) == {"runtime": "auto"}
    nc.Project.from_name("booking", create_if_missing=True).hydrate()
    assert patch.call_count == 1  # left out, never changed
    nc.Project.from_id("prj_1").update(runtime="container", framework=None)
    assert body(patch.calls.last.request) == {"runtime": "container", "framework": None}
    api.get("/v1/deployments/dep_2").respond(json={
        **DEPLOYMENT, "id": "dep_2", "runtime": "container", "runtime_reason": "a Dockerfile describes its server"})
    ran = nc.Deployment.get("dep_2")
    assert (ran.runtime, ran.runtime_reason) == ("container", "a Dockerfile describes its server")


def test_secrets_are_set_per_environment(api, client):
    put = api.put("/v1/projects/prj_1/secrets/STRIPE_KEY").respond(json={})
    listed = api.get("/v1/projects/prj_1/secrets").respond(json=listing(
        {"name": "STRIPE_KEY", "environments": ["preview"], "updated_at": "2026-09-25T10:00:00Z"}))
    delete = api.delete("/v1/projects/prj_1/secrets/STRIPE_KEY").respond(json={})

    app = nc.Project.from_id("prj_1")
    app.secrets.set("STRIPE_KEY", "sk_live_1", environment="production")
    assert body(put.calls.last.request) == {"value": "sk_live_1", "environment": "production"}
    app.secrets.set("STRIPE_KEY", "sk_test_1", environment="all")
    assert body(put.calls.last.request) == {"value": "sk_test_1"}
    assert list(app.secrets.list(environment="preview")) == ["STRIPE_KEY"]
    assert listed.calls.last.request.url.params["environment"] == "preview"
    app.secrets.list()
    assert "environment" not in listed.calls.last.request.url.params
    app.secrets.delete("STRIPE_KEY", environment="preview")
    assert delete.calls.last.request.url.params["environment"] == "preview"


def test_deploy_waits_for_a_ready_deployment(api, client):
    deploy = api.post("/v1/projects/prj_1/deployments").respond(
        202, json=operation(op_id="op_d", kind="project.deploy", status="queued"))
    api.get("/v1/operations/op_d/wait").respond(json=operation(
        op_id="op_d", kind="project.deploy", status="succeeded",
        result={**DEPLOYMENT, "id": "dep_2", "branch": "new-form", "production": False,
                "url": "https://new-form--booking.noclick.site"}))
    logs = api.get("/v1/deployments/dep_2/logs").respond(json=listing(
        {"at": "2026-09-25T10:00:01Z", "level": "info", "message": "Installing dependencies", "deployment_id": "dep_2"}))

    app = nc.Project.from_id("prj_1", user=USER_ID)
    op = app.deploy(branch="new-form", commit="a1b2c3d")
    assert isinstance(op, nc.Operation)
    assert body(deploy.calls.last.request) == {"branch": "new-form", "commit": "a1b2c3d"}
    assert deploy.calls.last.request.headers["NoClick-User"] == USER_ID
    preview = op.wait()
    assert isinstance(preview, nc.Deployment)
    assert (preview.url, preview.production, preview.ready_at.minute) == ("https://new-form--booking.noclick.site", False, 2)
    [line] = preview.logs(kind="build")
    assert logs.calls.last.request.url.params["kind"] == "build"
    assert isinstance(line, nc.LogLine) and str(line) == "Installing dependencies"
    assert logs.calls.last.request.headers["NoClick-User"] == USER_ID  # the operation's user

    app.deploy()
    assert body(deploy.calls.last.request) == {}


def test_a_failed_build_names_its_deployment(api, client):
    api.post("/v1/projects/prj_1/deployments").respond(
        202, json=operation(op_id="op_f", kind="project.deploy", status="queued"))
    api.get("/v1/operations/op_f/wait").respond(json=operation(
        op_id="op_f", kind="project.deploy", status="failed",
        error={"type": "operation_failed", "message": "The build failed: npm run build exited 1.",
               "deployment_id": "dep_9"}))
    with pytest.raises(nc.OperationFailed, match="The build failed") as failed:
        nc.Project.from_id("prj_1").deploy().wait()
    assert failed.value.deployment_id == "dep_9"


def test_deployments_rollback_promote_and_cancel(api, client):
    listed = api.get("/v1/projects/prj_1/deployments").respond(json=listing(
        DEPLOYMENT, {**DEPLOYMENT, "id": "dep_0", "production": False}))
    promote = api.post("/v1/deployments/dep_0/promote").respond(
        202, json=operation(op_id="op_p", kind="deployment.promote", status="running"))
    api.get("/v1/operations/op_p/wait").respond(json=operation(
        op_id="op_p", kind="deployment.promote", status="succeeded",
        result={**DEPLOYMENT, "id": "dep_0", "production": True}))
    cancel = api.post("/v1/deployments/dep_3/cancel").respond(json={**DEPLOYMENT, "id": "dep_3", "status": "canceled"})

    app = nc.Project.from_id("prj_1")
    current, previous = app.deployments(branch="main", limit=5)
    params = listed.calls.last.request.url.params
    assert (params["branch"], params["limit"]) == ("main", "5")
    assert current.production and not previous.production

    rolled = app.rollback(to=previous).wait()
    assert promote.call_count == 1 and rolled.production and rolled.id == "dep_0"
    app.rollback(to="dep_0")
    assert promote.call_count == 2

    stuck = nc.Deployment.from_id("dep_3")
    assert stuck.cancel() is stuck and stuck.status == "canceled"
    assert cancel.call_count == 1


CHECK = {"object": "deployment_check", "deployment_id": "dep_1", "url": "https://booking.noclick.site",
         "passed": False, "checked_at": "2026-09-25T09:05:00Z", "cost_usd": 0.0012, "paths": [
             {"path": "/", "url": "https://booking.noclick.site/", "ok": True, "problem": None, "status": 200,
              "load_ms": 840, "title": "Booking", "console_errors": [{"kind": "console", "message": "Analytics"}],
              "screenshot": {"object": "file", "id": "f_1", "name": "check-home.png", "url": "https://f.test/1.png",
                             "mime_type": "image/png"}},
             {"path": "/book", "url": "https://booking.noclick.site/book", "ok": False,
              "problem": "It answered 404.", "status": 404, "load_ms": 120, "title": "Not found",
              "console_errors": [], "screenshot": None}]}


def test_a_deployment_is_checked_promoted_by_force_and_reads_its_request_outcomes(api, client):
    check = api.post("/v1/deployments/dep_1/check").respond(
        202, json=operation(op_id="op_c", kind="deployment.check", status="running"))
    api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="deployment.check", status="succeeded", result=CHECK))
    promote = api.post("/v1/deployments/dep_1/promote").respond(
        202, json=operation(op_id="op_p", kind="deployment.promote", status="running"))
    requests = api.get("/v1/deployments/dep_1/requests").respond(json={
        "object": "request_outcomes", "deployment_id": "dep_1", "since": "2026-09-24T09:00:00Z",
        "until": "2026-09-25T09:00:00Z", "requests": 120, "sampled": False, "errors": 3, "error_rate": 0.025,
        "by_status": {"200": 117, "500": 3}, "slowest_routes": [
            {"method": "POST", "path": "/api/book", "requests": 20, "errors": 3, "p50_ms": 310.0, "p95_ms": 1200.0,
             "max_ms": 1900.0}]})

    deployment = nc.Deployment.from_id("dep_1")
    checked = deployment.check(["/", "/book"]).wait()
    assert body(check.calls.last.request) == {"paths": ["/", "/book"]}
    assert isinstance(checked, nc.DeploymentCheck) and checked.passed is False and checked.cost_usd == 0.0012
    home, book = checked.paths
    assert isinstance(home, nc.PathCheck) and (home.ok, home.status, home.load_ms) == (True, 200, 840)
    assert home.console_errors == [{"kind": "console", "message": "Analytics"}]
    assert home.screenshot["url"] == "https://f.test/1.png"
    assert (book.ok, book.problem, book.screenshot) == (False, "It answered 404.", None)
    deployment.check()
    assert check.calls.last.request.content == b""  # the app's own check paths

    deployment.promote()
    assert promote.calls.last.request.content == b""
    deployment.promote(force=True)
    assert body(promote.calls.last.request) == {"force": True}

    outcomes = deployment.requests()
    assert "since" not in requests.calls.last.request.url.params
    assert isinstance(outcomes, nc.RequestOutcomes)
    assert (outcomes.requests, outcomes.errors, outcomes.error_rate, outcomes.by_status) == (
        120, 3, 0.025, {"200": 117, "500": 3})
    [slowest] = outcomes.slowest_routes
    assert isinstance(slowest, nc.RouteTiming) and (slowest.path, slowest.p95_ms) == ("/api/book", 1200.0)
    deployment.requests(since="2026-09-20T00:00:00Z")
    assert requests.calls.last.request.url.params["since"] == "2026-09-20T00:00:00Z"


def test_bind_sends_name_kind_and_id(api, client):
    bind = api.post("/v1/projects/prj_1/bindings").mock(side_effect=lambda request: httpx.Response(200, json={
        "object": "binding", "name": body(request)["name"], "kind": body(request)["kind"],
        "resource_id": body(request)["id"], "resource_name": "booking-db", "created_at": "2026-09-25T10:00:00Z"}))
    listed = api.get("/v1/projects/prj_1/bindings").respond(json=listing(
        {"name": "DB", "kind": "database", "resource_id": "db_1", "resource_name": "booking-db",
         "variables": ["DB"], "created_at": "2026-09-25T10:00:00Z"},
        {"name": "SHIPPING", "kind": "secret", "resource_id": "sec_1", "resource_name": "shipping",
         "variables": ["SHIPPING_API_KEY"], "created_at": "2026-09-25T10:00:00Z"}))
    unbind = api.delete("/v1/projects/prj_1/bindings/CRM").respond(204)

    app = nc.Project.from_id("prj_1")
    made = app.bind("DB", nc.Database.from_id("db_1"))
    assert body(bind.calls.last.request) == {"name": "DB", "kind": "database", "id": "db_1"}
    assert isinstance(made, nc.Binding) and (made.name, made.kind, made.resource_id) == ("DB", "database", "db_1")
    app.bind("FILES", nc.Bucket.from_id("bkt_1"))
    assert body(bind.calls.last.request) == {"name": "FILES", "kind": "bucket", "id": "bkt_1"}
    app.bind("CRM", nc.Connection.from_id("con_1"))
    assert body(bind.calls.last.request) == {"name": "CRM", "kind": "connection", "id": "con_1"}
    app.bind("DB", "db_2", kind="database")
    assert body(bind.calls.last.request) == {"name": "DB", "kind": "database", "id": "db_2"}
    with pytest.raises(TypeError, match="kind="):
        app.bind("DB", "db_2")
    app.bind("SUPPORT", nc.Agent.from_id("agt_1"))
    assert body(bind.calls.last.request) == {"name": "SUPPORT", "kind": "agent", "id": "agt_1"}
    # The agent lists the apps that bind it.
    api.get("/v1/agents/agt_1").respond(json=agent_row(id="agt_1", name="support", used_by=[
        {"kind": "project", "id": "prj_1", "name": "booking", "binding": "SUPPORT"}]))
    assert nc.Agent.from_id("agt_1").used_by == [{"kind": "project", "id": "prj_1", "name": "booking",
                                                  "binding": "SUPPORT"}]
    with pytest.raises(TypeError, match="not Volume"):
        app.bind("DATA", nc.Volume.from_id("vol_1"))
    assert bind.call_count == 5

    binding, secret = app.bindings()
    assert (binding.name, binding.resource_name, binding.created_at.year) == ("DB", "booking-db", 2026)
    # What the code reads: a secret's keys under the binding's name.
    assert (binding.variables, secret.variables) == (["DB"], ["SHIPPING_API_KEY"])
    assert made.variables == []  # an answer that names none
    assert listed.call_count == 1
    app.unbind("CRM")
    assert unbind.call_count == 1


def test_secrets_are_write_only(api, client):
    put = api.put("/v1/projects/prj_1/secrets/MAPS_API_KEY").respond(204)
    api.get("/v1/projects/prj_1/secrets").respond(json=listing(
        {"name": "MAPS_API_KEY", "updated_at": "2026-09-25T10:00:00Z"},
        {"name": "SESSION_SECRET", "updated_at": "2026-09-20T10:00:00Z"}))
    delete = api.delete("/v1/projects/prj_1/secrets/MAPS_API_KEY").respond(204)

    app = nc.Project.from_id("prj_1", user=USER_ID)
    assert app.secrets.set("MAPS_API_KEY", "key_1") is None
    assert body(put.calls.last.request) == {"value": "key_1"}
    assert put.calls.last.request.headers["NoClick-User"] == USER_ID
    secrets = app.secrets.list()
    assert list(secrets) == ["MAPS_API_KEY", "SESSION_SECRET"] and secrets["MAPS_API_KEY"].day == 25
    app.secrets.delete("MAPS_API_KEY")
    assert delete.call_count == 1
    assert "key_1" not in repr(app.secrets)


def test_schedules_take_a_cron_and_a_path(api, client):
    create = api.post("/v1/projects/prj_1/schedules").respond(json=SCHEDULE)
    api.get("/v1/projects/prj_1/schedules").respond(json=listing(
        {**SCHEDULE, "status": "paused", "paused_reason": "5 identical failures in 30 minutes: 500 Internal Server Error",
         "last_status": "failed", "last_error": "Answered 500.", "last_run": "2026-09-25T13:00:00Z"}))
    pause = api.post("/v1/schedules/sch_1/pause").respond(json={**SCHEDULE, "status": "paused"})
    resume = api.post("/v1/schedules/sch_1/resume").respond(json=SCHEDULE)
    run = api.post("/v1/schedules/sch_1/run").respond(json={**SCHEDULE, "last_status": "succeeded",
                                                            "last_run": "2026-09-25T10:05:00Z"})
    delete = api.delete("/v1/schedules/sch_1").respond(204)

    app = nc.Project.from_id("prj_1")
    reminders = app.schedule(nc.Cron("0 9 * * 1-5", tz="America/New_York", message="for an agent"),
                             path="/jobs/reminders")
    # An app's schedule calls a path: a Cron's message (an agent's turn) isn't sent.
    assert body(create.calls.last.request) == {"cron": "0 9 * * 1-5", "tz": "America/New_York", "path": "/jobs/reminders"}
    assert isinstance(reminders, nc.Schedule) and reminders.next_run.hour == 13
    app.schedule(nc.Cron("0 * * * *"), path="/jobs/sync", name="hourly-sync")
    assert body(create.calls.last.request) == {"cron": "0 * * * *", "tz": "UTC", "path": "/jobs/sync", "name": "hourly-sync"}
    with pytest.raises(TypeError, match="noclick.Cron"):
        app.schedule("0 * * * *", path="/jobs/sync")

    [paused] = app.schedules()
    assert (paused.status, paused.last_status) == ("paused", "failed") and "identical failures" in paused.paused_reason
    assert paused.last_error == "Answered 500."
    assert paused.pause().status == "paused" and pause.call_count == 1
    assert paused.resume().status == "active" and resume.call_count == 1
    assert paused.run_now().last_status == "succeeded" and run.call_count == 1
    nc.Schedule.from_id("sch_1").delete()
    assert delete.call_count == 1


def test_domains_logs_usage_export_and_delete(api, client):
    domain = {"object": "domain", "id": "dom_1", "name": "acmebooking.com", "source": "bought", "status": "active",
              "records": [], "serves": [{"kind": "project", "id": "prj_1", "name": "booking"}], "user_id": None}
    add = api.post("/v1/projects/prj_1/domains").respond(json=domain)
    api.get("/v1/projects/prj_1/domains").respond(json=listing(domain))
    logs = api.get("/v1/projects/prj_1/logs").respond(json=listing(
        {"at": "2026-09-25T10:00:00Z", "level": "error", "message": "SQLITE_BUSY", "deployment_id": "dep_1",
         "environment": "preview", "request_id": "r1", "status": None}))
    api.get("/v1/projects/prj_1/usage").respond(json={
        "requests": 18342, "cpu_ms": 912000, "usd": 1.84, "period_start": "2026-09-01T00:00:00Z"})
    export = api.post("/v1/projects/prj_1/export").respond(202, json=operation(
        op_id="op_x", kind="project.export", status="running"))
    api.get("/v1/operations/op_x/wait").respond(json=operation(
        op_id="op_x", kind="project.export", status="succeeded",
        result={"url": "https://exports.noclick.app/booking.zip", "contents": [
            {"kind": "database", "name": "booking-db", "detail": "A SQL dump."}]}))
    delete = api.delete("/v1/projects/prj_1").respond(json=trashed("project", "prj_1", "booking"))

    removed = api.delete("/v1/projects/prj_1/domains/book.acme.com").respond(
        json={"object": "project_domain", "name": "book.acme.com", "deleted": True})

    app = nc.Project.from_id("prj_1")
    added = app.add_domain("acmebooking.com")
    assert body(add.calls.last.request) == {"name": "acmebooking.com"}
    assert isinstance(added, nc.Domain) and added.status == "active"
    assert [d.name for d in app.domains()] == ["acmebooking.com"]
    assert app.remove_domain("book.acme.com") is None and removed.call_count == 1

    from datetime import datetime, timezone

    [line] = app.logs(since=datetime(2026, 9, 25, 9, tzinfo=timezone.utc), level="error",
                      deployment=nc.Deployment.from_id("dep_1"), limit=50, environment="preview")
    params = logs.calls.last.request.url.params
    assert (params["since"], params["level"], params["deployment_id"], params["limit"], params["environment"]) == (
        "2026-09-25T09:00:00+00:00", "error", "dep_1", "50", "preview")
    assert (line.level, line.message, line.deployment_id) == ("error", "SQLITE_BUSY", "dep_1")
    assert (line.environment, line.request_id, line.status) == ("preview", "r1", None)
    app.logs()
    assert dict(logs.calls.last.request.url.params) == {"limit": "100"}

    used = app.usage()
    assert isinstance(used, nc.ProjectUsage)
    assert (used.requests, used.cpu_ms, used.usd, used.period_start.month) == (18342, 912000, 1.84, 9)
    assert (used.budget_usd, used.limited_by, used.by_type) == (None, None, {})

    bundle = app.export().wait()
    assert export.called and isinstance(bundle, nc.ExportBundle) and bundle.contents[0].name == "booking-db"

    item = app.delete()
    assert "delete_data" not in delete.calls.last.request.url.params
    assert isinstance(item, nc.TrashItem) and (item.kind, item.resource_id) == ("project", "prj_1")
    app.delete(delete_data=True)
    assert delete.calls.last.request.url.params["delete_data"] == "true"


def test_usage_refuses_a_missing_number(api, client):
    api.get("/v1/projects/prj_1/usage").respond(json={"requests": 1, "usd": 0.1})
    with pytest.raises(nc.Error, match="cpu_ms"):
        nc.Project.from_id("prj_1").usage()


# --- an app at run time: its budget, its AI and its agent -------------------------

def test_a_budget_is_part_of_the_app_definition(api, client):
    api.get("/v1/projects").respond(json=listing({**PROJECT, "budget_usd_per_month": 10}))
    create = api.post("/v1/projects").mock(side_effect=lambda request: httpx.Response(200, json={**PROJECT, **body(request)}))
    patch = api.patch("/v1/projects/prj_1").mock(
        side_effect=lambda request: httpx.Response(200, json={**PROJECT, **body(request)}))

    app = nc.Project.create("booking", repo="repo_1", budget_usd_per_month=25)
    assert body(create.calls.last.request) == {"name": "booking", "repo_id": "repo_1", "budget_usd_per_month": 25}
    assert app.budget_usd_per_month == 25
    nc.Project.create("status-page")
    assert "budget_usd_per_month" not in body(create.calls.last.request)

    defined = nc.Project.from_name("booking", repo="repo_1", budget_usd_per_month=25, create_if_missing=True)
    assert defined.budget_usd_per_month == 25
    assert body(patch.calls.last.request) == {"budget_usd_per_month": 25}  # only what differs
    nc.Project.from_name("booking", repo="repo_1", create_if_missing=True).hydrate()
    assert patch.call_count == 1  # a budget left out is never changed
    nc.Project.from_name("booking", budget_usd_per_month=None, create_if_missing=True).hydrate()
    assert body(patch.calls.last.request) == {"budget_usd_per_month": None}  # None removes it

    app = nc.Project.from_id("prj_1")
    assert app.update(budget_usd_per_month=50, repo=nc.Repo.from_id("repo_2"), production_branch="release") is app
    assert body(patch.calls.last.request) == {"production_branch": "release", "budget_usd_per_month": 50,
                                              "repo_id": "repo_2"}
    assert (app.budget_usd_per_month, app.production_branch, app.repo_id) == (50, "release", "repo_2")
    app.update(budget_usd_per_month=None)
    assert body(patch.calls.last.request) == {"budget_usd_per_month": None}


def test_usage_shows_spend_against_the_budget_and_what_stops_it(api, client):
    api.get("/v1/projects/prj_1/usage").respond(json={
        "requests": 18342, "cpu_ms": 912000, "usd": 25.04, "period_start": "2026-10-01T00:00:00Z",
        "budget_usd": 25, "limited_by": "project",
        "by_type": {"apps": 1.84, "ai": 14.2, "model_tokens": 6.9, "tool_runs": 1.1, "databases": 0.6, "app_email": 0.4}})
    used = nc.Project.from_id("prj_1").usage()
    assert (used.usd, used.budget_usd, used.limited_by) == (25.04, 25, "project")
    assert used.by_type["ai"] == 14.2 and sum(used.by_type.values()) == pytest.approx(used.usd)


ANALYTICS = {
    "object": "project_analytics", "project_id": "prj_1", "period": "7d", "environment": "production",
    "interval": "day", "tz": "Europe/Paris", "since": "2026-10-09T22:00:00+00:00", "until": "2026-10-16T09:00:00+00:00",
    "requests": 1204, "errors": 3, "error_rate": 0.0025, "by_status": {"200": 1180, "404": 21, "500": 3},
    "by_source": {"browser": 1100, "automated": 104}, "noclick_requests": 12, "p50_ms": 42.0, "p95_ms": 310.5,
    "series": [{"at": "2026-10-09T22:00:00+00:00", "requests": 160, "errors": 0},
               {"at": "2026-10-10T22:00:00+00:00", "requests": 1044, "errors": 3}],
    "top_paths": [{"path": "/", "requests": 600, "browser_requests": 540, "errors": 0, "p95_ms": 120.0},
                  {"path": "/api/book", "requests": 90, "browser_requests": 88, "errors": 3, "p95_ms": None}],
    "previous_requests": 980, "previous_errors": 7, "sampled": False,
}


def test_analytics_reads_the_apps_traffic_by_day_against_the_period_before(api, client):
    read = api.get("/v1/projects/prj_1/analytics").respond(json=ANALYTICS)
    app = nc.Project.from_id("prj_1")
    week = app.analytics(tz="Europe/Paris")
    assert dict(read.calls.last.request.url.params) == {"period": "7d", "environment": "production",
                                                         "tz": "Europe/Paris"}
    assert isinstance(week, nc.ProjectAnalytics)
    assert (week.requests, week.previous_requests, week.errors, week.error_rate) == (1204, 980, 3, 0.0025)
    assert (week.interval, week.p50_ms, week.p95_ms, week.by_status["404"]) == ("day", 42.0, 310.5, 21)
    first, second = week.series
    assert isinstance(first, nc.TrafficInterval) and first.at.isoformat() == "2026-10-09T22:00:00+00:00"
    assert (second.requests, second.errors) == (1044, 3)
    home, api_path = week.top_paths
    assert isinstance(home, nc.PathTraffic) and (home.path, home.requests, home.p95_ms) == ("/", 600, 120.0)
    assert home.browser_requests == 540
    assert (week.by_source, week.noclick_requests) == ({"browser": 1100, "automated": 104}, 12)
    assert (api_path.errors, api_path.p95_ms) == (3, None)
    app.analytics(period="24h", environment="all")
    assert dict(read.calls.last.request.url.params) == {"period": "24h", "environment": "all"}


def test_analytics_summary_reads_every_apps_week_at_once(api, client):
    read = api.get("/v1/projects/analytics/summary").respond(json={
        "object": "project_analytics_summary", "period": "7d", "tz": "Europe/Paris",
        "since": "2026-10-09T22:00:00+00:00", "until": "2026-10-16T09:00:00+00:00", "sampled": False,
        "data": [{"project_id": "prj_2", "requests": 0, "browser_requests": 0, "errors": 0, "noclick_requests": 6},
                 {"project_id": "prj_1", "requests": 1204, "browser_requests": 1100, "errors": 3,
                  "noclick_requests": 12}]})
    week = nc.Project.analytics_summary(tz="Europe/Paris", user_filter=nc.NO_USER)
    assert dict(read.calls.last.request.url.params) == {"period": "7d", "tz": "Europe/Paris", "user_id": "none"}
    assert "NoClick-User" not in read.calls.last.request.headers
    assert isinstance(week, nc.AnalyticsSummary) and [a.project_id for a in week.apps] == ["prj_2", "prj_1"]
    one = week.of(nc.Project.from_id("prj_1"))
    assert isinstance(one, nc.AppRequests) and (one.requests, one.errors) == (1204, 3)
    assert (one.browser_requests, one.noclick_requests) == (1100, 12)
    assert week.of("prj_gone").requests == 0
    with nc.as_user("user_42"):
        nc.Project.analytics_summary(period="30d")
    assert read.calls.last.request.headers["NoClick-User"] == "user_42"
    assert dict(read.calls.last.request.url.params) == {"period": "30d"}


def _deployed(api, monkeypatch):
    monkeypatch.setenv("NOCLICK_DEPLOYMENT_TOKEN", "nk_dep_123")
    monkeypatch.setenv("NOCLICK_API_URL", BASE)
    api.get("/v1/projects/current").respond(json=PROJECT)
    return nc.Project.current()


def test_the_running_app_talks_to_its_agent_as_itself(api, client, monkeypatch):
    api.get("/v1/projects/prj_1/bindings/SUPPORT").respond(json={
        "name": "SUPPORT", "kind": "agent", "resource_id": "ag_1", "resource_name": "support"})
    api.get("/v1/projects/prj_1/bindings/DB").respond(json={"name": "DB", "kind": "database", "resource_id": "db_1"})
    api.get("/v1/agents/ag_1").respond(json=agent_row())
    send = api.post("/v1/agents/ag_1/messages").respond(202, json=operation(
        op_id="op_t", kind="agent.message", status="running"))
    api.get("/v1/operations/op_t/wait").respond(json=operation(
        op_id="op_t", kind="agent.message", status="succeeded",
        result={"text": "Saturday at 10 works. Moved.", "conversation": "app:prj_1:visitor-91c2"}))

    app = _deployed(api, monkeypatch)
    support = app.agent("SUPPORT")
    assert isinstance(support, nc.Agent) and support.name == "support"
    reply = support.message("Can I move my booking to Saturday?", conversation="visitor-91c2")
    # The thread is the app's own, which its code may pass back as it is or by its own key.
    assert (reply.text, reply.conversation) == ("Saturday at 10 works. Moved.", "app:prj_1:visitor-91c2")
    request = send.calls.last.request
    assert request.headers["Authorization"] == "Bearer nk_dep_123" and "NoClick-User" not in request.headers
    assert body(request) == {"text": "Can I move my booking to Saturday?", "conversation": "visitor-91c2"}
    with pytest.raises(nc.InvalidRequest, match="bound to a database, not an agent"):
        app.agent("DB")


def test_a_users_app_reaches_what_is_bound_to_it_without_naming_the_user_its_credential_acts_for(
        api, client, monkeypatch):
    owner = "wa-120363"
    binding = api.get("/v1/projects/prj_1/bindings/DB").respond(json={
        "name": "DB", "kind": "database", "resource_id": "db_1"})
    api.get("/v1/projects/prj_1/bindings/SUPPORT").respond(json={
        "name": "SUPPORT", "kind": "agent", "resource_id": "ag_1"})
    loaded = api.get("/v1/databases/db_1").respond(json={
        "object": "database", "id": "db_1", "name": "notes", "user_id": owner})
    query = api.post("/v1/databases/db_1/query").respond(json={
        "object": "query_result", "columns": ["n"], "rows": [{"n": 1}]})
    api.get("/v1/agents/ag_1").respond(json=agent_row(user_id=owner))
    send = api.post("/v1/agents/ag_1/messages").respond(202, json=operation(
        op_id="op_t", kind="agent.message", status="running"))
    api.get("/v1/operations/op_t/wait").respond(json=operation(
        op_id="op_t", kind="agent.message", status="succeeded", result={"text": "Hi"}))

    monkeypatch.setitem(PROJECT, "user_id", owner)
    app = _deployed(api, monkeypatch)
    db = app.database("DB")
    db.query("select 1 as n")
    db.hydrate()  # what it loads names its user, which still isn't sent
    db.query("select 1 as n")
    app.agent("SUPPORT").message("Hello", conversation="visitor-1")
    sent = [binding.calls.last, loaded.calls.last, *query.calls, send.calls.last]
    for call in sent:
        assert call.request.headers["Authorization"] == "Bearer nk_dep_123"
        assert "NoClick-User" not in call.request.headers, call.request.url
    # With a key of your own, the same database's calls name its user.
    mine = nc.Database.from_id("db_1", user=None).hydrate()
    mine.query("select 1 as n")
    assert query.calls.last.request.headers["NoClick-User"] == owner


def test_app_ai_is_noclick_ai_acting_as_the_app(api, client, monkeypatch):
    chat = api.post("/v1/ai/chat/completions").respond(
        headers={"content-type": "text/event-stream"},
        content=('data: {"choices": [{"index": 0, "delta": {"content": "Great class, cold room."}, '
                 '"finish_reason": "stop"}], "cost_usd": 0.0002}\n\ndata: [DONE]\n\n').encode())
    embed = api.post("/v1/ai/embeddings").respond(json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    models = api.get("/v1/ai/models").respond(json=listing({"id": "agent:support", "kind": "agent"}))

    with pytest.raises(nc.InvalidRequest, match="Project.current"):
        nc.Project.from_id("prj_1").ai.chat("Hi")  # your key never spends as the app
    assert chat.call_count == 0

    app = _deployed(api, monkeypatch)
    reply = app.ai.chat("Summarize in one line: the class was great but the room was cold.", max_tokens=60)
    assert (reply.text, reply.cost_usd) == ("Great class, cold room.", 0.0002)
    request = chat.calls.last.request
    assert request.headers["Authorization"] == "Bearer nk_dep_123" and "NoClick-User" not in request.headers
    assert body(request)["max_tokens"] == 60
    assert app.ai.embed("yoga").vectors == [[0.1, 0.2]] and body(embed.calls.last.request)["input"] == ["yoga"]
    [bound] = app.ai.models(kind="agent")
    assert bound.id == "agent:support" and models.calls.last.request.url.params["kind"] == "agent"
    assert app.ai.base_url == f"{BASE}/v1/ai"
    assert app.ai.headers() == {"Authorization": "Bearer nk_dep_123"}


def test_a_paid_call_past_the_budget_names_the_app(api, client, monkeypatch):
    api.post("/v1/ai/chat/completions").respond(402, json={"error": {
        "type": "spend_cap_exceeded", "message": "booking reached its $25.00 monthly budget.",
        "next_step": "Raise it with app.update(budget_usd_per_month=...), or wait until it resets on Nov 1.",
        "scope": "project", "cap": 25, "spent": 25.04, "project_id": "prj_1", "project": "booking"}})
    app = _deployed(api, monkeypatch)
    with pytest.raises(nc.SpendCapExceeded) as refused:
        app.ai.chat("Summarize: ...")
    err = refused.value
    assert (err.scope, err.cap, err.spent, err.project, err.project_id) == ("project", 25, 25.04, "booking", "prj_1")
    assert "budget_usd_per_month" in err.next_step


def test_usage_limits_list_app_budgets_and_spend_groups_by_app(api, client):
    api.get("/v1/usage/limits").respond(json={
        "period_start": "2026-10-01T00:00:00Z", "resets_at": "2026-11-01T00:00:00Z", "keys": [], "users": [],
        "agents": [], "projects": [{"id": "prj_1", "name": "booking", "user_id": None, "budget": 25, "spent": 25.04}]})
    grouped = api.get("/v1/usage").respond(json={"period": "month", "total_usd": 25.04, "group_by": "project",
                                                 "groups": [{"id": "prj_1", "usd": 25.04, "events": 812}]})
    [budget] = nc.Usage.limits().projects
    assert isinstance(budget, nc.ProjectBudget)
    assert (budget.id, budget.name, budget.user_id, budget.budget, budget.spent) == ("prj_1", "booking", None, 25, 25.04)
    month = nc.usage(group_by="project")
    assert grouped.calls.last.request.url.params["group_by"] == "project" and month["prj_1"].usd == 25.04


def test_operations_resume_typed_anywhere(api, client):
    api.get("/v1/operations/op_d/wait").respond(json=operation(
        op_id="op_d", kind="project.deploy", status="succeeded", result=DEPLOYMENT))
    api.get("/v1/operations/op_g/wait").respond(json=operation(
        op_id="op_g", kind="repo.export_to_github", status="succeeded", result={"url": "https://github.com/a/b"}))
    assert isinstance(nc.Operation.from_id("op_d").wait(), nc.Deployment)
    assert nc.Operation.from_id("op_g").wait() == "https://github.com/a/b"


async def test_aio_forms(api, client):
    api.get("/v1/repos/repo_1/branches").respond(json=listing({"name": "main", "head": "9f2c1ab"}))
    api.get("/v1/projects/prj_1/schedules").respond(json=listing(SCHEDULE))
    [branch] = await nc.Repo.from_id("repo_1").branches.aio()
    [schedule] = await nc.Project.from_id("prj_1").schedules.aio()
    assert (branch.name, schedule.path) == ("main", "/jobs/reminders")


def test_deploy_on_push_is_part_of_the_definition_and_deployments_say_what_started_them(api, client):
    create = api.post("/v1/projects").respond(json={**PROJECT, "deploy_on_push": "production"})
    lookup = api.get("/v1/projects").respond(json=listing({**PROJECT, "deploy_on_push": "off"}))
    patch = api.patch("/v1/projects/prj_1").respond(json={**PROJECT, "deploy_on_push": "all"})
    api.get("/v1/projects/prj_1/deployments").respond(json=listing(
        {**DEPLOYMENT, "status": "failed", "started_by": "push", "error": "The app's budget is used up."}))

    app = nc.Project.create("booking", repo="repo_1", runtime="container", framework="python",
                            deploy_on_push="production")
    assert body(create.calls.last.request) == {"name": "booking", "repo_id": "repo_1", "runtime": "container",
                                               "framework": "python", "deploy_on_push": "production"}
    assert app.deploy_on_push == "production"
    defined = nc.Project.from_name("booking", deploy_on_push="all", create_if_missing=True)
    assert defined.deploy_on_push == "all" and lookup.call_count == 1
    assert body(patch.calls.last.request) == {"deploy_on_push": "all"}
    nc.Project.from_name("booking", create_if_missing=True).hydrate()
    assert patch.call_count == 1  # left out, never changed
    nc.Project.from_id("prj_1").update(deploy_on_push="all")
    assert body(patch.calls.last.request) == {"deploy_on_push": "all"}
    [refused] = nc.Project.from_id("prj_1").deployments()
    assert (refused.started_by, refused.status, refused.error) == ("push", "failed", "The app's budget is used up.")

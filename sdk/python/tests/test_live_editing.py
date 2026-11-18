"""An app edited live: its switch, its session started (once, with the link that opens it in live mode), commands run
in it with what each edit did in the open pages, its edits read back, and its end, which deploys only once its build
and check pass."""

import httpx
import pytest

import noclick as nc
from platform_helpers import body, operation

PROJECT = {"object": "project", "id": "prj_1", "name": "larkspur", "url": "https://larkspur.noclick.site",
           "repo_id": "repo_1", "production_branch": "main", "preview_resources": "branch", "check_paths": [],
           "live_editing": False, "live_editing_set_by": None, "production": None, "user_id": None,
           "created_at": "2026-10-20T10:00:00Z"}
HOT = {"seq": 12, "boot": "b-7f3a", "at": 1793040000180, "files": ["src/render.js"], "outcome": "hot",
       "updates": [{"type": "js-update", "path": "/src/render.js", "acceptedPath": "/src/render.js"}],
       "clients": 2, "applied": {"ok": 2, "failed": 0, "errors": []}}
RELOAD = {"seq": 13, "boot": "b-7f3a", "at": 1793040003000, "files": ["src/main.js"], "outcome": "reload",
          "reload": {"path": "*", "triggeredBy": "/src/main.js", "reason": "no-boundary",
                     "chain": ["/src/main.js", "/index.html"]}, "clients": 1}
ERROR = {"seq": 14, "boot": "b-7f3a", "at": 1793040007000, "files": ["src/update.js"], "outcome": "error",
         "error": {"message": "Unexpected token", "file": "/site/src/update.js", "loc": {"line": 4, "column": 9},
                   "plugin": "vite:esbuild"}, "clients": 1}
SESSION = {"object": "live_session", "id": "ls_1", "project_id": "prj_1", "state": "live", "phase": None,
           "boot_id": "b-7f3a", "workdir": "/site", "mode": "vite", "url": "https://larkspur.noclick.site",
           "viewers": {"connected": 1, "visible": 1},
           "git": {"branch": "noclick-live", "head": None, "pushed": None, "dirty": False, "state": "clean"},
           "data": [{"kind": "database", "name": "DB", "production_id": "db_1", "copy_id": None, "with_data": True,
                     "note": "A copy with production's data, made at the session's first write."}],
           "readiness": {"ready": True, "mode": "vite", "reasons": []},
           "edits": {"count": 3, "hot": 2, "reload": 1, "error": 0, "last_seq": 13},
           "timings": {"live_ms": 4300}, "where": {"do_colo": "IAD", "container_colo": "IAD"},
           "worker_version": "v1", "started_at": "2026-10-27T09:00:00Z", "live_at": "2026-10-27T09:00:04Z",
           "ended_at": None, "end_reason": None, "error": None, "release": None, "needs_source": None,
           "limits": {"idle_grace_s": 30, "idle_end_s": 30, "max_quiet_with_viewers_s": 14400, "max_session_s": 43200,
                      "hold_warming_s": 30}}
ENTER_URL = "https://larkspur.noclick.site/__noclick/live/3hK9qLm2ZxR7tVb4NcW8pY"


def test_the_switch_turns_live_editing_on_and_says_what_keeps_an_app_from_it(api, client):
    patch = api.patch("/v1/projects/prj_1").mock(
        side_effect=lambda request: httpx.Response(200, json={**PROJECT, **body(request), "live_editing_set_by": "owner"}))
    app = nc.Project.from_id("prj_1")
    assert app.update(live_editing=True) is app
    assert body(patch.calls.last.request) == {"live_editing": True}
    assert (app.live_editing, app.live_editing_set_by) == (True, "owner")

    api.get("/v1/projects/prj_1/live").respond(json={
        "object": "live", "project_id": "prj_1", "enabled": True, "supported": True, "session": SESSION,
        "attached": [{"agent_id": "ag_1", "conversation": "owner"}]})
    status = app.live.status()
    assert (status.enabled, status.supported, status.unsupported_reason) == (True, True, None)
    assert status.attached == [{"agent_id": "ag_1", "conversation": "owner"}]
    session = status.session
    assert isinstance(session, nc.LiveSession) and session.open
    assert (session.state, session.mode, session.workdir, session.viewers) == (
        "live", "vite", "/site", {"connected": 1, "visible": 1})
    assert session.edits == nc.LiveEditCounts(count=3, hot=2, reload=1, error=0, last_seq=13)
    assert session.data == [nc.LiveDataCopy(
        kind="database", name="DB", production_id="db_1", copy_id=None, with_data=True,
        note="A copy with production's data, made at the session's first write.")]
    assert session.live_at.isoformat() == "2026-10-27T09:00:04+00:00" and session.ended_at is None
    assert session.git["state"] == "clean" and session.limits["idle_end_s"] == 30

    # An app it can't run on says why, and has had no session.
    api.get("/v1/projects/prj_2/live").respond(json={
        "object": "live", "project_id": "prj_2", "enabled": False, "supported": False,
        "unsupported_reason": "Live editing works with apps on the edge for now.", "session": None, "attached": []})
    other = nc.Project.from_id("prj_2").live.status()
    assert (other.supported, other.unsupported_reason, other.session) == (
        False, "Live editing works with apps on the edge for now.", None)

    api.patch("/v1/projects/prj_3").respond(409, json={"error": {
        "type": "conflict", "message": "A live session writes only to copies of the app's data.",
        "next_step": 'PATCH the app with "preview_resources": "branch" too.'}})
    with pytest.raises(nc.Conflict, match="copies of the app's data"):
        nc.Project.from_id("prj_3").update(live_editing=True)


def test_a_session_starts_once_with_the_link_that_opens_it_and_shortens_its_timers(api, client):
    start = api.post("/v1/projects/prj_1/live/sessions").respond(json={**SESSION, "enter_url": ENTER_URL})
    live = nc.Project.from_id("prj_1").live
    session = live.start()
    assert body(start.calls.last.request) is None  # nothing asked: the server's defaults
    assert (session.id, session.enter_url, session.url) == ("ls_1", ENTER_URL, "https://larkspur.noclick.site")

    # Waiting answers the session as it stands once the request has waited as long as it may: still warming.
    start.respond(json={**SESSION, "state": "warming", "phase": "starting_container", "live_at": None,
                        "enter_url": ENTER_URL})
    warming = live.start(wait=True, refresh_data=True, limits={"idle_grace_s": 30, "idle_end_s": 30})
    assert body(start.calls.last.request) == {
        "wait": True, "refresh_data": True, "limits": {"idle_grace_s": 30, "idle_end_s": 30}}
    assert (warming.state, warming.phase, warming.open, warming.live_at) == (
        "warming", "starting_container", True, None)

    link = api.post("/v1/projects/prj_1/live/enter_links").respond(
        json={"url": ENTER_URL, "expires_at": "2026-10-27T11:00:00Z"})
    made = live.enter_link()
    assert body(link.calls.last.request) is None
    assert (made.url, made.expires_at.isoformat()) == (ENTER_URL, "2026-10-27T11:00:00+00:00")


def test_a_command_runs_in_the_session_and_says_what_each_edit_did(api, client):
    run = api.post("/v1/projects/prj_1/live/exec").respond(json={
        "stdout": "", "stderr": "", "exit_code": 0, "ms": 412, "truncated": {"stdout": False, "stderr": False},
        "written_at": 1793040000123, "vite": [HOT, RELOAD], "earlier": [ERROR]})
    result = nc.Project.from_id("prj_1").live.exec("sed -i 's/Score/Points/' src/render.js", timeout_s=30)
    assert body(run.calls.last.request) == {"command": "sed -i 's/Score/Points/' src/render.js", "timeout_s": 30}
    assert (result.ok, result.exit_code, result.timed_out, result.ms) == (True, 0, False, 412)
    hot, reload = result.vite
    assert (hot.outcome, hot.files, hot.clients, hot.applied) == (
        "hot", ["src/render.js"], 2, {"ok": 2, "failed": 0, "errors": []})
    assert (reload.outcome, reload.reload["reason"], reload.reload["chain"]) == (
        "reload", "no-boundary", ["/src/main.js", "/index.html"])
    assert [(e.seq, e.outcome, e.error["message"]) for e in result.earlier] == [(14, "error", "Unexpected token")]

    # A failing command is a result, and the default timeout is the most a command answered in its request runs.
    run.respond(json={"stdout": "", "stderr": "sed: can't read src/x.js", "exit_code": 2, "ms": 8,
                      "truncated": {"stdout": False, "stderr": False}, "written_at": None, "vite": []})
    failed = nc.Project.from_id("prj_1").live.exec("sed -i 's/a/b/' src/x.js")
    assert body(run.calls.last.request) == {"command": "sed -i 's/a/b/' src/x.js", "timeout_s": 90}
    assert (failed.ok, failed.vite, failed.earlier, str(failed)) == (False, [], [], "")

    # A session still starting refuses a command answered in its request: it didn't run.
    run.respond(409, json={"error": {
        "type": "conflict", "state": "warming",
        "message": "The app's live session is still starting, so the command didn't run.",
        "next_step": "Run it again in a minute, or with background: true."}})
    with pytest.raises(nc.Conflict, match="didn't run") as refused:
        nc.Project.from_id("prj_1").live.exec("npm test")
    assert refused.value.state == "warming"


def test_a_long_command_or_one_for_a_starting_session_runs_in_the_background(api, client):
    run = api.post("/v1/projects/prj_1/live/exec").respond(
        202, json=operation(op_id="op_x", kind="project.live_exec", status="queued"))
    api.get("/v1/operations/op_x/wait").respond(json=operation(
        op_id="op_x", kind="project.live_exec", status="succeeded", result={
            "stdout": "added 1 package", "stderr": "", "exit_code": 0, "ms": 41250,
            "truncated": {"stdout": False, "stderr": False}, "written_at": 1793040041250, "vite": [RELOAD]}))
    op = nc.Project.from_id("prj_1").live.exec("npm install canvas-confetti", background=True, timeout_s=300)
    assert isinstance(op, nc.Operation) and op.kind == "project.live_exec"
    assert body(run.calls.last.request) == {
        "command": "npm install canvas-confetti", "background": True, "timeout_s": 300}
    installed = op.wait()
    assert isinstance(installed, nc.LiveExecResult)
    assert (installed.ok, installed.stdout, installed.ms) == (True, "added 1 package", 41250)
    assert [edit.reload["reason"] for edit in installed.vite] == ["no-boundary"]


def test_edits_read_back_a_page_at_a_time(api, client):
    read = api.get("/v1/projects/prj_1/live/edits").respond(json={
        "object": "list", "data": [HOT, RELOAD, ERROR], "last_seq": 14})
    edits = nc.Project.from_id("prj_1").live.edits()
    assert [e.outcome for e in edits] == ["hot", "reload", "error"] and edits.last_seq == 14
    assert dict(read.calls.last.request.url.params) == {"limit": "50"}
    assert edits[2].error["loc"] == {"line": 4, "column": 9}

    read.respond(json={"object": "list", "data": [], "last_seq": 14})
    later = nc.Project.from_id("prj_1").live.edits(after=14, limit=10)
    assert dict(read.calls.last.request.url.params) == {"after": "14", "limit": "10"}
    assert (list(later), later.last_seq) == ([], 14)


def test_the_end_deploys_only_what_passed_and_waits_like_any_operation(api, client):
    end = api.post("/v1/projects/prj_1/live/end").respond(
        202, json=operation(op_id="op_e", kind="project.live_end", status="queued"))
    api.get("/v1/operations/op_e/wait").respond(json=operation(
        op_id="op_e", kind="project.live_end", status="succeeded", result={
            "object": "live_end", "project_id": "prj_1", "session_id": "ls_1", "outcome": "deployed",
            "deployment_id": "dep_7"}))
    op = nc.Project.from_id("prj_1").live.end()
    assert isinstance(op, nc.Operation) and op.kind == "project.live_end"
    assert body(end.calls.last.request) == {"deploy": True}
    ended = op.wait()
    assert isinstance(ended, nc.LiveEnd)
    assert (ended.outcome, ended.session_id, ended.deployment_id, ended.main_behind) == (
        "deployed", "ls_1", "dep_7", False)

    nc.Project.from_id("prj_1").live.end(deploy=False)
    assert body(end.calls.last.request) == {"deploy": False}

    # A build or check that failed fails the operation: production was never touched.
    api.get("/v1/operations/op_e/wait").respond(json=operation(
        op_id="op_e", kind="project.live_end", status="failed", error={
            "type": "operation_failed",
            "message": "What the live session edited wasn't deployed: It failed its check: / answered 500."}))
    with pytest.raises(nc.OperationFailed, match="wasn't deployed"):
        nc.Operation.from_id("op_e").wait()

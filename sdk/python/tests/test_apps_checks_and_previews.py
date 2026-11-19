"""An app's check paths that ask its API, what a deploy and a preview say about themselves, the checks that wait,
sign in and review, where a deployment serves, how far behind a log read can be, and sign-in committed without a
deploy."""

import httpx

import noclick as nc
from platform_helpers import body, listing, operation

DEPLOYMENT = {"object": "deployment", "id": "dep_1", "project_id": "prj_1", "branch": "main", "commit": "9f2c1ab",
              "commit_message": "Add the booking form", "status": "ready", "url": "https://booking.noclick.site",
              "production": True, "environment": "production", "error": None,
              "serves": {"production": "https://booking.noclick.site", "preview": None},
              "created_at": "2026-09-25T09:01:00Z", "ready_at": "2026-09-25T09:02:10Z"}
PROJECT = {"object": "project", "id": "prj_1", "name": "booking", "url": "https://booking.noclick.site",
           "repo_id": "repo_1", "production_branch": "main", "preview_resources": "branch", "check_paths": [],
           "production": DEPLOYMENT, "user_id": None, "created_at": "2026-09-20T10:00:00Z"}
CHECK_PATHS = ["/", {"path": "/api/health", "status": 200}, {"path": "/api/bookings", "json": True}]


def test_an_app_is_made_with_its_preview_data_and_check_paths_and_kept_to_them(api, client):
    create = api.post("/v1/projects").respond(json={**PROJECT, "check_paths": CHECK_PATHS})
    app = nc.Project.create("booking", repo="repo_1", preview_resources="shared", check_paths=CHECK_PATHS)
    assert body(create.calls.last.request) == {
        "name": "booking", "repo_id": "repo_1", "preview_resources": "shared", "check_paths": CHECK_PATHS}
    assert app.check_paths == CHECK_PATHS

    # Your code is the definition: an app whose check paths or preview resources differ is brought in step.
    api.get("/v1/projects").respond(json=listing(PROJECT))
    patch = api.patch("/v1/projects/prj_1").mock(
        side_effect=lambda request: httpx.Response(200, json={**PROJECT, **body(request)}))
    defined = nc.Project.from_name("booking", preview_resources="shared", check_paths=CHECK_PATHS,
                                   create_if_missing=True)
    assert defined.preview_resources == "shared"
    assert body(patch.calls.last.request) == {"preview_resources": "shared", "check_paths": CHECK_PATHS}
    api.get("/v1/projects").respond(json=listing({**PROJECT, "check_paths": CHECK_PATHS}))
    nc.Project.from_name("booking", check_paths=list(CHECK_PATHS), create_if_missing=True).hydrate()
    assert patch.call_count == 1  # the same paths change nothing

    nc.Project.from_id("prj_1").update(check_paths=[{"path": "/api/health", "status": 204}])
    assert body(patch.calls.last.request) == {"check_paths": [{"path": "/api/health", "status": 204}]}


def test_a_deploy_says_whether_its_code_answered_and_what_a_preview_writes_to(api, client):
    deploy = api.post("/v1/projects/prj_1/deployments").respond(
        202, json=operation(op_id="op_d", kind="project.deploy", status="queued"))
    preview_data = ("This preview writes to its own copy of DB (database) and any other database, bucket, dict or "
                    "queue its code reaches, made at its first write.")
    unchecked = "Static files answered every path asked (/), so the app's server code never ran."
    api.get("/v1/operations/op_d/wait").respond(json=operation(
        op_id="op_d", kind="project.deploy", status="succeeded", result={
            **DEPLOYMENT, "id": "dep_2", "branch": "new-form", "production": False, "environment": "preview",
            "url": "https://new-form--booking.noclick.site",
            "serves": {"production": None, "preview": "https://new-form--booking.noclick.site"},
            "code_unchecked": unchecked, "preview_data": preview_data}))
    preview = nc.Project.from_id("prj_1").deploy(branch="new-form").wait()
    assert body(deploy.calls.last.request) == {"branch": "new-form"}
    assert (preview.code_unchecked, preview.preview_data, preview.warning) == (unchecked, preview_data, None)
    assert preview.serves == {"production": None, "preview": "https://new-form--booking.noclick.site"}

    api.get("/v1/operations/op_d/wait").respond(json=operation(
        op_id="op_d", kind="project.deploy", status="succeeded", result={
            **DEPLOYMENT, "warning": "It's live, but https://booking.noclick.site/api/health answered 500, not 200.",
            "next_step": "Read the app's runtime log, fix the cause, then deploy again."}))
    live = nc.Project.from_id("prj_1").deploy().wait()
    assert live.warning.endswith("answered 500, not 200.") and live.code_unchecked is None
    assert live.next_step == "Read the app's runtime log, fix the cause, then deploy again."
    assert live.preview_data is None and preview.next_step is None

    # A deployment read later names where it serves, and a promoted preview serves both.
    api.get("/v1/deployments/dep_3").respond(json={
        **DEPLOYMENT, "id": "dep_3", "environment": "preview",
        "serves": {"production": "https://booking.noclick.site", "preview": "https://new-form--booking.noclick.site"},
        "check": {"operation_id": "op_c", "passed": True, "url": "https://booking.noclick.site",
                  "checked_at": "2026-09-25T09:05:00Z", "paths": [], "code_unchecked": unchecked}})
    promoted = nc.Deployment.get("dep_3")
    assert promoted.serves["production"] == "https://booking.noclick.site" and promoted.environment == "preview"
    assert promoted.last_check["code_unchecked"] == unchecked and promoted.warning is None


CHECK = {"object": "deployment_check", "deployment_id": "dep_1", "url": "https://booking.noclick.site",
         "passed": False, "checked_at": "2026-09-25T09:05:00Z", "cost_usd": 0.0042, "paths": [
             {"path": "/", "url": "https://booking.noclick.site/", "ok": False,
              "problem": "A picture it shows doesn't load: /images/hero.jpg.", "status": 200, "load_ms": 840,
              "title": "Booking", "broken_images": ["/images/hero.jpg"], "console_errors": [],
              "screenshot": {"object": "file", "id": "f_1", "url": "https://f.test/1.png"},
              "undeliverable_emails": ["hello@bistro.invalid-domain.com"]},
             {"path": "/api/health", "url": "https://booking.noclick.site/api/health", "ok": True, "problem": None,
              "status": 200, "load_ms": 95, "title": None, "broken_images": [], "console_errors": [],
              "screenshot": None, "undeliverable_emails": [], "expected": {"status": 200}}],
         "review": {"model": "openrouter/anthropic/claude-haiku-5.5", "scores": {"task": 4, "forms": 3},
                    "issues": [{"where": "/", "what": "The date field has no label", "fix": "Label it"}],
                    "passed": False, "cost_usd": 0.003}}


def test_a_check_asks_requests_waits_signs_in_and_reviews(api, client):
    check = api.post("/v1/deployments/dep_1/check").respond(
        202, json=operation(op_id="op_c", kind="deployment.check", status="running"))
    api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="deployment.check", status="succeeded", result=CHECK))

    deployment = nc.Deployment.from_id("dep_1")
    checked = deployment.check(
        ["/", {"path": "/api/health", "status": 200}],
        review={"brief": "A booking page for one bistro", "rubric": "app"}, wait_for="main#booking", settle_ms=2500,
        headers={"Authorization": "Bearer test-session"}, cookies=[{"name": "session", "value": "s_1"}],
    ).wait()
    assert body(check.calls.last.request) == {
        "paths": ["/", {"path": "/api/health", "status": 200}],
        "review": {"brief": "A booking page for one bistro", "rubric": "app"}, "wait_for": "main#booking",
        "settle_ms": 2500, "headers": {"Authorization": "Bearer test-session"},
        "cookies": [{"name": "session", "value": "s_1"}]}

    page, health = checked.paths
    assert (page.ok, page.broken_images, page.undeliverable_emails, page.expected) == (
        False, ["/images/hero.jpg"], ["hello@bistro.invalid-domain.com"], None)
    assert (health.ok, health.expected, health.screenshot, health.load_ms) == (True, {"status": 200}, None, 95)
    review = checked.review
    assert isinstance(review, nc.CheckReview)
    assert (review.passed, review.scores, review.claims, review.error, review.cost_usd) == (
        False, {"task": 4, "forms": 3}, [], None, 0.003)
    assert [issue["fix"] for issue in review.issues] == ["Label it"]
    assert checked.code_unchecked is None

    # Its code never ran: every path passed from the release's files.
    api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="deployment.check", status="succeeded",
        result={**CHECK, "passed": True, "review": None, "code_unchecked": "Static files answered every path."}))
    passed = deployment.check(["/"]).wait()
    assert body(check.calls.last.request) == {"paths": ["/"]}
    assert (passed.code_unchecked, passed.review) == ("Static files answered every path.", None)

    deployment.check(review={"brief": "A bistro in Lyon", "facts": "Open 7-11pm"})
    assert body(check.calls.last.request) == {"review": {"brief": "A bistro in Lyon", "facts": "Open 7-11pm"}}
    deployment.check()
    assert check.calls.last.request.content == b""  # the app's own check paths


def test_a_review_that_couldnt_answer_says_why(api, client):
    api.post("/v1/deployments/dep_1/check").respond(
        202, json=operation(op_id="op_c", kind="deployment.check", status="running"))
    api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="deployment.check", status="succeeded", result={
            **CHECK, "review": {"model": "openrouter/anthropic/claude-haiku-5.5",
                                "error": "No page loaded, so there was nothing to look at.", "cost_usd": 0.0}}))
    review = nc.Deployment.from_id("dep_1").check(["/"], review={"brief": "A bistro"}).wait().review
    assert (review.passed, review.scores, review.issues, review.error) == (
        None, {}, [], "No page loaded, so there was nothing to look at.")


def test_log_reads_say_how_far_behind_they_can_be(api, client):
    line = {"at": "2026-09-25T10:00:00Z", "level": "error", "message": "GET /api/health -> 500",
            "deployment_id": "dep_1", "environment": "preview", "request_id": "r1", "status": 500}
    app_logs = api.get("/v1/projects/prj_1/logs").respond(json={**listing(line), "delay_s": 60})
    lines = nc.Project.from_id("prj_1").logs(environment="preview")
    assert isinstance(lines, nc.LogLines) and isinstance(lines, list)
    assert (lines.delay_s, lines[0].status, lines[0].request_id) == (60, 500, "r1")
    assert app_logs.calls.last.request.url.params["environment"] == "preview"

    runtime = api.get("/v1/deployments/dep_1/logs").respond(json={**listing(line), "delay_s": 30})
    tail = nc.Deployment.from_id("dep_1").logs(kind="runtime", level="error", environment="production", limit=5)
    assert dict(runtime.calls.last.request.url.params) == {
        "kind": "runtime", "level": "error", "environment": "production", "limit": "5"}
    assert tail.delay_s == 30 and [str(t) for t in tail] == ["GET /api/health -> 500"]

    # A build's log is kept whole as it's written: no delay to speak of.
    api.get("/v1/deployments/dep_1/logs").respond(json=listing({**line, "level": "info", "message": "Building"}))
    build = nc.Deployment.from_id("dep_1").logs()
    assert dict(runtime.calls.last.request.url.params) == {"kind": "build"}
    assert build.delay_s is None and build[0].message == "Building"


def test_sign_in_commits_without_deploying_when_asked(api, client):
    enable = api.post("/v1/projects/prj_1/sign_in").respond(
        json=operation(kind="project.sign_in.enable", status="running"))
    upgrade = api.post("/v1/projects/prj_1/sign_in/upgrade").respond(
        json=operation(kind="project.sign_in.upgrade", status="running"))
    app = nc.Project.from_id("prj_1")
    app.sign_in.enable(["email"], deploy=False)
    assert body(enable.calls.last.request) == {"providers": ["email"], "users_table": "users", "deploy": False}
    app.sign_in.enable(["email"])
    assert "deploy" not in body(enable.calls.last.request)  # deployed, as before
    app.sign_in.upgrade(deploy=False)
    assert body(upgrade.calls.last.request) == {"deploy": False}
    app.sign_in.upgrade(branch="sign-in-update")
    assert body(upgrade.calls.last.request) == {"branch": "sign-in-update"}


def test_an_apps_previews_are_kept_to_a_link_and_its_deploy_and_owner_hand_it_out(api, client):
    said = "Its previews stay public until NoClick's front door is updated."
    patch = api.patch("/v1/projects/prj_1").mock(
        side_effect=lambda request: httpx.Response(200, json={**PROJECT, **body(request), "notes": [said]}))
    app = nc.Project.from_id("prj_1").update(preview_access="link", preview_public_paths=("/api/webhooks/*",))
    assert body(patch.calls.last.request) == {"preview_access": "link", "preview_public_paths": ["/api/webhooks/*"]}
    assert (app.preview_access, app.preview_public_paths, app.raw["notes"]) == ("link", ["/api/webhooks/*"], [said])

    link_url = "https://new-form--booking.noclick.site/?preview=p1~1800604800~prj_1~new-form--booking.noclick.site~ab"
    made = api.post("/v1/projects/prj_1/previews/link").respond(json={
        "object": "preview_link", "project_id": "prj_1", "branch": "new-form", "url": link_url,
        "preview_url": "https://new-form--booking.noclick.site", "preview_access": "link",
        "expires_at": "2027-01-21T08:00:00Z"})
    link = app.preview_link(branch="new-form", expires_in=3600)
    assert body(made.calls.last.request) == {"branch": "new-form", "expires_in": 3600}
    assert (link.url, link.branch, link.preview_url, link.preview_access) == (
        link_url, "new-form", "https://new-form--booking.noclick.site", "link")
    assert link.expires_at.year == 2027
    app.preview_link()
    assert body(made.calls.last.request) == {}

    api.post("/v1/projects/prj_1/deployments").respond(
        202, json=operation(op_id="op_p", kind="project.deploy", status="queued"))
    api.get("/v1/operations/op_p/wait").respond(json=operation(
        op_id="op_p", kind="project.deploy", status="succeeded", result={
            **DEPLOYMENT, "id": "dep_3", "branch": "new-form", "production": False, "environment": "preview",
            "url": "https://new-form--booking.noclick.site", "preview_link": link_url}))
    preview = app.deploy(branch="new-form").wait()
    assert (preview.url, preview.preview_link) == ("https://new-form--booking.noclick.site", link_url)
    assert nc.Deployment._new(raw=DEPLOYMENT).preview_link is None


def test_stopping_an_apps_preview_links_answers_the_app_with_what_it_did(api, client):
    said = "Every link to its previews made before now stops opening them within 30 seconds."
    stop = api.post("/v1/projects/prj_1/previews/links/revoke").respond(
        json={**PROJECT, "preview_access": "link", "notes": [said]})
    app = nc.Project.from_id("prj_1")
    assert app.revoke_preview_links() is app
    assert stop.called and stop.calls.last.request.content in (b"", b"{}")
    assert (app.preview_access, app.raw["notes"]) == ("link", [said])

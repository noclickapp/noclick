"""An app's code made public (``Project.make_public``), taken back (``make_private``), and what anyone may know of an
address (``PublicApp.lookup``)."""

import httpx

import noclick as nc
from platform_helpers import body

PROJECT = {"object": "project", "id": "prj_1", "name": "pilot-hub", "url": "https://pilot-hub.noclick.site",
           "repo_id": "repo_1", "production_branch": "main", "production": None, "public": None, "user_id": None,
           "created_at": "2026-11-20T10:00:00Z"}
PUBLIC = {"object": "public_app", "public": True, "clone_url": "https://pilot-hub.noclick.site",
          "origin_url": "https://api.noclick.com/v1/public/git/3f2a1b0c-9d8e-4f7a-8b6c-5d4e3f2a1b0c.git",
          "commit": {"sha": "a" * 40, "source_commit": "b" * 40, "published_at": "2026-11-23T08:00:00Z"},
          "files": 12, "license": None, "forks": 0, "transfer_cap_usd": 5.0, "blocked": False,
          "summary": "Anyone will be able to clone pilot-hub's code ...", "scanned": {"files": 12, "findings": []}}


def test_an_app_is_made_public_after_a_dry_run_and_private_again(api, client):
    api.get("/v1/projects/prj_1").respond(json=PROJECT)
    route = api.post("/v1/projects/prj_1/public").mock(side_effect=lambda request: httpx.Response(200, json=(
        {"object": "public_app_preview", "public": False, "would_publish": False, "address": PROJECT["url"],
         "commit": "b" * 40, "files": 12, "summary": "...",
         "scanned": {"files": 12, "findings": [{"path": ".env", "why": "its name, .env, ..."}]}}
        if body(request).get("dry_run") else PUBLIC)))
    app = nc.Project.from_id("prj_1")
    preview = app.make_public(dry_run=True)
    assert body(route.calls.last.request) == {"dry_run": True}
    assert (preview.would_publish, preview.findings[0]["path"], preview.public) == (False, ".env", False)

    made = app.make_public(transfer_cap_usd=2)
    assert body(route.calls.last.request) == {"transfer_cap_usd": 2}
    assert (made.public, made.clone_url, made.commit_sha, made.forks) == (True, PROJECT["url"], "a" * 40, 0)

    api.delete("/v1/projects/prj_1/public").respond(json={
        "object": "public_app", "public": False, "was_public": True, "note": "Copies people already cloned stay."})
    private = app.make_private()
    assert (private.public, private.summary) == (False, "Copies people already cloned stay.")


def test_an_apps_view_says_whether_its_code_is_public(api, client):
    api.get("/v1/projects/prj_1").respond(json={**PROJECT, "public": PUBLIC})
    shown = nc.Project.from_id("prj_1").public
    assert shown is not None and shown.origin_url.endswith(".git")
    api.get("/v1/projects/prj_2").respond(json={**PROJECT, "id": "prj_2"})
    assert nc.Project.from_id("prj_2").public is None


def test_anyone_looks_an_address_up(api, client):
    route = api.get("/v1/public/apps").respond(json={
        "object": "public_app", "address": "pilot-hub.noclick.site", "public": True, "name": "pilot-hub",
        "title": "Pilot hub", "clone_url": PROJECT["url"], "origin_url": PUBLIC["origin_url"], "default_branch": "main",
        "commit": {"sha": "a" * 40, "published_at": "2026-11-23T08:00:00Z"}, "forks": 3, "license": "MIT",
        "deploy": {"account_key_scopes": ["apps"], "build_env": [], "secrets": []}, "report": "support@noclick.com"})
    found = nc.PublicApp.lookup("pilot-hub.noclick.site")
    assert route.calls.last.request.url.params["address"] == "pilot-hub.noclick.site"
    assert (found.public, found.clone_url, found.forks, found.deploy["account_key_scopes"]) == (
        True, PROJECT["url"], 3, ["apps"])

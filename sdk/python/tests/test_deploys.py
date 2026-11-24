"""Deploying a repository in one call: what the client sends (a URL or one of your repos, the secrets you set, the
key you give, a dry run) and what it reads back (the plan, the operation, the live app), and reading a password
NoClick made once, against the mocked transport."""

import pytest

import noclick as nc
from platform_helpers import body, operation
from test_estimates import ESTIMATE

PLAN = {
    "object": "deploy_plan", "dry_run": True,
    "source": {"kind": "url", "url": "https://gitlab.com/acme/tools/console", "ref": None, "host": "gitlab.com",
               "path": "acme/tools/console", "commit": "a" * 40, "branch": "main", "default_branch": "main"},
    "name": "console", "runtime": "edge", "framework": None, "reason": "it's only files", "noclick_json": True,
    "account_key": {"scopes": ["agents", "dicts"], "given_by": "deploy", "at_deploy": "asks_owner",
                    "can": [{"scope": "agents", "can": "run your agents", "reads_secrets": False},
                            {"scope": "dicts", "can": "read your dicts", "reads_secrets": False}],
                    "cannot": ["make keys"], "note": "Anyone who can change this app's code acts with this key.",
                    "variable": "NOCLICK_API_KEY"},
    "secrets": {"generated": [{"name": "APP_PASSWORD", "kind": "password", "description": None, "shown_once": True}],
                "asked": [{"name": "STRIPE_SECRET_KEY", "description": "Your Stripe key", "required": True,
                           "given": False}]},
    "missing_secrets": ["STRIPE_SECRET_KEY"], "refused": None, "estimate": ESTIMATE, "funds": {"ok": True},
    "makes": ["repo", "project"],
}
RESULT = {"object": "deploy_result", "project_id": "prj_1", "name": "console", "url": "https://console.noclick.site",
          "repo_id": "repo_1", "deployment_id": "dep_1", "commit": "a" * 40,
          "account_key": {"status": "waiting", "missing_scopes": [], "request": {"approval_id": "apr_1"}},
          "secrets": {"to_reveal": [{"name": "APP_PASSWORD", "expires_at": "2026-12-01T10:00:00Z"}],
                      "next_step": "Read it once."}}


def test_a_dry_run_sends_the_url_and_reads_what_the_deploy_would_do(api, client):
    route = api.post("/v1/deploys").respond(json=PLAN)
    plan = nc.deploy("https://gitlab.com/acme/tools/console", dry_run=True)
    assert body(route.calls.last.request) == {"source": {"url": "https://gitlab.com/acme/tools/console"},
                                              "dry_run": True}
    assert isinstance(plan, nc.DeployPlan)
    assert (plan.name, plan.runtime, plan.noclick_json, plan.makes) == ("console", "edge", True, ["repo", "project"])
    assert plan.source["commit"] == "a" * 40 and plan.estimate.monthly_usd == 0.311
    assert plan.account_key.scopes == ["agents", "dicts"] and plan.account_key.given_by == "deploy"
    assert plan.account_key.at_deploy == "asks_owner" and plan.account_key.can[0]["can"] == "run your agents"
    assert [(s.name, s.generate, s.required, s.given, s.shown_once) for s in plan.secrets] == [
        ("APP_PASSWORD", "password", True, False, True), ("STRIPE_SECRET_KEY", None, True, False, False)]
    assert plan.missing_secrets == ["STRIPE_SECRET_KEY"] and plan.funds == {"ok": True} and plan.refused is None


def test_a_deploy_sends_what_you_bring_and_waits_for_the_live_app(api, client):
    route = api.post("/v1/deploys").respond(status_code=202, json={
        "object": "deploy", "name": "console-live", "source": PLAN["source"],
        "operation": operation(op_id="op_d", kind="repo.deploy", status="queued")})
    api.get("/v1/operations/op_d/wait").respond(json=operation(op_id="op_d", kind="repo.deploy", status="succeeded",
                                                               result=RESULT))
    op = nc.deploy("https://gitlab.com/acme/tools/console", ref="v2", name="console-live",
                   secrets={"STRIPE_SECRET_KEY": "sk_live_1"}, account_key=["agents", "dicts"],
                   key_spend_cap_usd_per_month=5)
    assert body(route.calls.last.request) == {
        "source": {"url": "https://gitlab.com/acme/tools/console", "ref": "v2"}, "name": "console-live",
        "secrets": {"STRIPE_SECRET_KEY": "sk_live_1"},
        "account_key": {"scopes": ["agents", "dicts"], "spend_cap_usd_per_month": 5}}
    assert isinstance(op, nc.RepoDeploy) and isinstance(op, nc.Operation)
    done = op.wait()
    assert isinstance(done, nc.DeployResult)
    assert (done.project_id, done.url, done.repo_id, done.to_reveal) == (
        "prj_1", "https://console.noclick.site", "repo_1", ["APP_PASSWORD"])
    assert done.account_key["status"] == "waiting"


@pytest.mark.parametrize("source, sent", [
    ("console", {"repo": "console"}),
    ("4c1d6a3e-0b0e-4a3b-9f6b-0a1c2e3f4a5b", {"repo": "4c1d6a3e-0b0e-4a3b-9f6b-0a1c2e3f4a5b"}),
    ("git@github.com:acme/site.git", {"url": "git@github.com:acme/site.git"}),
])
def test_your_own_repo_by_name_or_id_goes_as_repo_and_anything_like_a_url_as_url(api, client, source, sent):
    route = api.post("/v1/deploys").respond(json=PLAN)
    nc.deploy(source, dry_run=True)
    assert body(route.calls.last.request)["source"] == sent


def test_a_repo_object_goes_by_its_id(api, client):
    route = api.post("/v1/deploys").respond(json=PLAN)
    nc.deploy(nc.Repo.from_id("repo_9"), dry_run=True)
    assert body(route.calls.last.request)["source"] == {"repo": "repo_9"}


def test_nothing_to_deploy_is_refused_before_anything_is_sent(api, client):
    with pytest.raises(ValueError):
        nc.deploy("  ", dry_run=True)


def test_a_password_noclick_made_is_read_once(api, client):
    route = api.post("/v1/projects/prj_1/secrets/APP_PASSWORD/reveal").respond(json={
        "object": "project_secret_value", "name": "APP_PASSWORD", "value": "kq7rm-x2p9d-tvh4c-8nwe3",
        "note": "Shown this once."})
    assert nc.Project.from_id("prj_1").secrets.reveal("APP_PASSWORD") == "kq7rm-x2p9d-tvh4c-8nwe3"
    assert route.call_count == 1

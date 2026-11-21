"""An interface step's app, published with no build (``Step.publish``, ``Step.rename_app``, ``Step.unpublish``): the
body each call sends and how the answer reads, against the mocked transport."""

import noclick as nc
from platform_helpers import body

PUBLISHED = {"object": "step_publication", "workflow_id": "wf_1", "step_id": "page", "action": "publish",
             "state": "published", "url": "https://morrow.noclick.app", "project_id": "prj_1", "subdomain": "morrow",
             "deployment_id": "dep_1", "previous_url": None, "trash_id": None, "restorable_until": None}


def test_publish_names_the_subdomain_the_first_time_and_reads_the_app(api, client):
    route = api.post("/v1/workflows/wf_1/steps/page/publish").respond(json=PUBLISHED)
    with nc.as_user("user_42"):
        done = nc.Workflow.from_id("wf_1").step("page").publish("morrow", title="Morrow Bakehouse")
    sent = route.calls.last.request
    assert body(sent) == {"action": "publish", "subdomain": "morrow", "title": "Morrow Bakehouse"}
    # Always the account's: its app isn't a user's.
    assert "NoClick-User" not in sent.headers
    assert isinstance(done, nc.StepPublication)
    assert (done.state, done.url, done.project_id, done.subdomain, done.deployment_id) == (
        "published", "https://morrow.noclick.app", "prj_1", "morrow", "dep_1")
    nc.Workflow.from_id("wf_1").step("page").publish()
    assert body(route.calls.last.request) == {"action": "publish"}


def test_rename_and_unpublish_say_where_it_was_and_how_it_comes_back(api, client):
    route = api.post("/v1/workflows/wf_1/steps/page/publish")
    route.respond(json={**PUBLISHED, "action": "rename", "state": "renamed", "url": "https://morrow-bakery.noclick.app",
                        "subdomain": "morrow-bakery", "deployment_id": None,
                        "previous_url": "https://morrow.noclick.app"})
    step = nc.Workflow.from_id("wf_1").step("page")
    moved = step.rename_app("morrow-bakery")
    assert body(route.calls.last.request) == {"action": "rename", "subdomain": "morrow-bakery"}
    assert (moved.state, moved.url, moved.previous_url) == (
        "renamed", "https://morrow-bakery.noclick.app", "https://morrow.noclick.app")

    route.respond(json={**PUBLISHED, "action": "unpublish", "state": "unpublished", "url": None,
                        "previous_url": "https://morrow-bakery.noclick.app", "trash_id": "trash_9",
                        "restorable_until": "2026-12-21T10:00:00+00:00"})
    gone = step.unpublish()
    assert body(route.calls.last.request) == {"action": "unpublish"}
    assert (gone.state, gone.url, gone.trash_id, gone.restorable_until.month) == ("unpublished", None, "trash_9", 12)

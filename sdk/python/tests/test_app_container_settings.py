"""An app's container settings: what each instance gets and how many are kept warm, made with it, changed (only the
settings given, or all back to their defaults), read back with what its warm instances cost idle, and refused by the
setting that's out of bounds."""

import httpx
import pytest

import noclick as nc
from platform_helpers import body

DEFAULTS = {"cpu": 1.0, "memory": 512, "min_instances": 0, "max_instances": 10, "cpu_always": False,
            "request_timeout_s": 300, "idle_usd_per_month": 0.0, "note": None}
WARM_NOTE = "1 instance kept warm while production serves it: about $49.93 a month even with nothing calling it."
APPLIES = "Its container settings apply from its next release."
PROJECT = {"object": "project", "id": "prj_1", "name": "standup-bot", "url": "https://standup-bot.noclick.site",
           "repo_id": "repo_1", "runtime": "container", "production_branch": "main", "container": DEFAULTS,
           "production": None, "user_id": None, "created_at": "2026-09-20T10:00:00Z"}


def test_an_app_is_made_with_its_container_settings_and_reads_them_back(api, client):
    bot = {**DEFAULTS, "cpu_always": True, "min_instances": 1, "idle_usd_per_month": 49.93, "note": WARM_NOTE}
    create = api.post("/v1/projects").respond(json={**PROJECT, "container": bot})
    app = nc.Project.create("standup-bot", repo="repo_1", runtime="container",
                            container={"cpu_always": True, "min_instances": 1})
    assert body(create.calls.last.request) == {
        "name": "standup-bot", "repo_id": "repo_1", "runtime": "container",
        "container": {"cpu_always": True, "min_instances": 1}}
    container = app.container
    assert isinstance(container, nc.ProjectContainer)
    assert (container.cpu, container.memory, container.min_instances, container.max_instances) == (1.0, 512, 1, 10)
    assert (container.cpu_always, container.request_timeout_s) == (True, 300)
    assert (container.idle_usd_per_month, container.note) == (49.93, WARM_NOTE)

    # Without settings, none are sent: the app runs at the defaults.
    nc.Project.create("standup-bot-2", repo="repo_1")
    assert "container" not in body(create.calls.last.request)


def _patched(request):
    """The app as a PATCH leaves it: the settings given over the defaults, or the defaults again for None."""
    given = body(request).get("container", {})
    return httpx.Response(200, json={**PROJECT, "notes": [APPLIES], "container": {**DEFAULTS, **(given or {})}})


def test_an_update_sends_only_the_settings_given_and_none_resets_them(api, client):
    patch = api.patch("/v1/projects/prj_1").mock(side_effect=_patched)
    app = nc.Project.from_id("prj_1").update(container={"cpu": 2, "memory": 4096})
    assert body(patch.calls.last.request) == {"container": {"cpu": 2, "memory": 4096}}
    assert (app.container.cpu, app.container.memory, app.raw["notes"]) == (2, 4096, [APPLIES])

    # Another app's settings carry over as settings alone, not what they cost.
    other = nc.ProjectContainer._from({**DEFAULTS, "min_instances": 1, "idle_usd_per_month": 9.86, "note": "warm"})
    nc.Project.from_id("prj_1").update(container=other)
    assert body(patch.calls.last.request) == {"container": {
        "cpu": 1.0, "memory": 512, "min_instances": 1, "max_instances": 10, "cpu_always": False,
        "request_timeout_s": 300}}

    reset = nc.Project.from_id("prj_1").update(container=None)
    assert body(patch.calls.last.request) == {"container": None}
    assert reset.container.min_instances == 0 and reset.container.note is None

    # Nothing about the container is sent when it isn't given.
    nc.Project.from_id("prj_1").update(budget_usd_per_month=25)
    assert body(patch.calls.last.request) == {"budget_usd_per_month": 25}

    with pytest.raises(TypeError, match="mapping of settings"):
        nc.Project.from_id("prj_1").update(container=2)


def test_a_setting_out_of_bounds_is_refused_by_name(api, client):
    api.patch("/v1/projects/prj_1").respond(400, json={"error": {
        "type": "invalid_request", "message": "container.memory: 1 vCPU takes 512 to 4096 MiB of memory, not 8192: "
        "change cpu with it.", "field": "container.memory"}})
    with pytest.raises(nc.InvalidRequest) as refused:
        nc.Project.from_id("prj_1").update(container={"memory": 8192})
    assert refused.value.field == "container.memory"

    api.patch("/v1/projects/prj_1").respond(400, json={"error": {
        "type": "invalid_request", "field": "container.min_instances", "idle_usd_per_month": 29.57,
        "message": "Keeping 3 instances warm costs about $29.57 a month with nothing calling the app, more than its "
                   "$10.00 budget: it would pause for it."}})
    with pytest.raises(nc.InvalidRequest) as over_budget:
        nc.Project.from_id("prj_1").update(container={"min_instances": 3})
    assert over_budget.value.field == "container.min_instances"
    assert over_budget.value.idle_usd_per_month == 29.57

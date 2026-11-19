"""Estimates: what the client sends to price things before they're made, and what it reads back, against the
mocked transport."""

import pytest

import noclick as nc
from platform_helpers import body, listing

LINE = {"description": "Each request through the front door.", "unit": "million requests", "usage_fields": ["requests"]}
ESTIMATE = {
    "object": "estimate", "estimated": True, "monthly_usd": 0.311,
    "plan": {"name": "free", "billing": "at_cost", "included_usd_per_month": 5.0, "included_usd_per_day": 1.0},
    "included_usd_per_month": 5.0,
    "items": [
        {"kind": "project", "label": "App on the edge", "name": "site",
         "options": {"runtime": "edge", "region": "us-east", "framework": None},
         "usage": {"requests": 100000.0, "code_share": 0.2}, "assumed": ["framework", "code_share"],
         "monthly_usd": 0.202,
         "lines": [{**LINE, "charge": "front_door", "unit_usd": 1.9, "quantity": 0.1, "usd": 0.19, "assumed": False},
                   {**LINE, "charge": "code_runs", "unit": "million runs", "unit_usd": 0.6, "quantity": 0.02,
                    "usd": 0.012, "assumed": True, "usage_fields": ["requests", "code_share"]}],
         "not_included": ["The front door's CPU time."]},
        {"kind": "database", "label": "SQLite database", "name": None, "options": {"engine": "sqlite"},
         "usage": {"rows_written": 100000.0}, "assumed": ["engine"], "monthly_usd": 0.1,
         "lines": [{**LINE, "charge": "rows_written", "unit": "million rows", "unit_usd": 1.0, "quantity": 0.1,
                    "usd": 0.1, "assumed": True, "usage_fields": ["rows_written"]}],
         "not_included": []},
    ],
}
KIND = {
    "object": "estimate_kind", "kind": "bucket", "label": "Bucket", "description": "A storage bucket for files.",
    "options": {},
    "usage": [{"name": "storage_gb", "unit": "GB", "description": "What it stores.", "default": 1.0, "most": None}],
    "prices": [{"charge": "storage", "description": "What it stores.", "unit": "GB-month", "unit_usd": 0.015,
                "usage_fields": ["storage_gb"]}],
    "not_included": [],
}


def test_an_estimate_sends_the_items_and_reads_every_line(api, client):
    route = api.post("/v1/estimates").respond(json=ESTIMATE)
    items = [{"kind": "project", "name": "site", "usage": {"requests": 100_000}}, {"kind": "database"}]
    est = nc.estimate(items)
    assert body(route.calls.last.request) == {"items": items}
    assert (est.monthly_usd, est.estimated, est.included_usd_per_month) == (0.311, True, 5.0)
    assert (est.plan["name"], est.plan["included_usd_per_day"]) == ("free", 1.0)
    site, database = est.items
    assert (site.kind, site.label, site.name, site.options["runtime"], site.assumed, site.monthly_usd) == (
        "project", "App on the edge", "site", "edge", ["framework", "code_share"], 0.202)
    assert site.usage == {"requests": 100000.0, "code_share": 0.2}
    assert site.not_included == ["The front door's CPU time."] and database.name is None
    # Every item's lines, in order, each saying which item it's for.
    assert [(line.kind, line.item, line.charge, line.quantity, line.unit_usd, line.usd, line.assumed)
            for line in est.lines] == [("project", "site", "front_door", 0.1, 1.9, 0.19, False),
                                       ("project", "site", "code_runs", 0.02, 0.6, 0.012, True),
                                       ("database", None, "rows_written", 0.1, 1.0, 0.1, True)]
    assert est.lines[1].unit == "million runs" and est.lines[1].raw["usage_fields"] == ["requests", "code_share"]


def test_a_container_app_is_priced_at_its_settings_with_what_its_warm_instances_cost_idle(api, client):
    note = "1 instance kept warm while production serves it: about $49.93 a month even with nothing calling it."
    settings = {"cpu": 1.0, "memory": 512, "min_instances": 1, "max_instances": 10, "cpu_always": True,
                "request_timeout_s": 300}
    bot = {"kind": "project", "label": "App in a container", "name": "bot", "assumed": ["region"],
           "options": {"runtime": "container", "region": "us-east", "framework": None, "container": settings},
           "usage": {"requests": 10000.0}, "monthly_usd": 50.06, "idle_usd_per_month": 49.93, "note": note,
           "lines": [{**LINE, "charge": "warm_instances", "unit": "instance-month", "unit_usd": 49.93,
                      "quantity": 1.0, "usd": 49.93, "assumed": False, "usage_fields": []}],
           "not_included": []}
    route = api.post("/v1/estimates").respond(json={**ESTIMATE, "monthly_usd": 50.06, "items": [bot]})
    items = [{"kind": "project", "runtime": "container", "name": "bot",
              "container": {"cpu_always": True, "min_instances": 1}}]
    [item] = nc.estimate(items).items
    assert body(route.calls.last.request) == {"items": items}
    assert (item.idle_usd_per_month, item.note, item.options["container"]) == (49.93, note, settings)
    assert [line.charge for line in item.lines] == ["warm_instances"]

    # Any other item has neither.
    route.respond(json=ESTIMATE)
    site = nc.estimate([{"kind": "project"}]).items[0]
    assert (site.idle_usd_per_month, site.note) == (None, None)


def test_an_estimate_for_a_user_says_who_and_names_no_plan(api, client):
    route = api.post("/v1/estimates").respond(json={**ESTIMATE, "plan": None, "included_usd_per_month": None})
    with nc.as_user("user_42"):
        est = nc.estimate([{"kind": "bucket"}])
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (est.plan, est.included_usd_per_month) == (None, None)


def test_the_kinds_say_each_usage_its_default_and_each_price(api, client):
    route = api.get("/v1/estimates/kinds").respond(json=listing(KIND))
    [bucket] = nc.Estimate.kinds(region="eu")
    assert route.calls.last.request.url.params["region"] == "eu"
    assert (bucket.kind, bucket.label, bucket.options) == ("bucket", "Bucket", {})
    assert bucket.usage == [nc.EstimateUsageField("storage_gb", "GB", "What it stores.", 1.0, None)]
    assert bucket.prices == [nc.EstimatePrice("storage", "What it stores.", "GB-month", 0.015, ["storage_gb"])]
    nc.Estimate.kinds()
    assert "region" not in route.calls.last.request.url.params


def test_what_it_cannot_price_is_refused_by_name(api, client):
    api.post("/v1/estimates").respond(400, json={"error": {
        "type": "invalid_request", "message": "items[0].usage.requests: a number, 0 or more, not -5.",
        "field": "items[0].usage.requests", "next_step": "Send it as a number, like 100000."}})
    with pytest.raises(nc.InvalidRequest) as refused:
        nc.estimate([{"kind": "project", "usage": {"requests": -5}}])
    assert refused.value.details["field"] == "items[0].usage.requests"
    with pytest.raises(TypeError):
        nc.estimate({"kind": "bucket"})

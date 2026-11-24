"""The account's ledger (parity with the TypeScript client, test/usage_ledger.test.ts): its groups read in a time
zone, a page of its charges narrowed and paged, and the money behind it, null where nobody is billed."""

import datetime
import json

import noclick as nc

UTC = datetime.timezone.utc

GROUP = {
    "current": True, "day": "2026-11-19", "created_at": "2026-11-19T09:00:00+00:00", "k": "k1", "user_id": "u1",
    "usage_type": "api_usage", "usage_subtype": "voice/call", "unit_type": "seconds", "user_resource": False, "n": 2,
    "quantity": 240.0, "total_cost": 0.5, "prompt_tokens": 0, "completion_tokens": 0, "workflow_id": None,
    "number": "+14155550132",
}
LEDGER = {
    "object": "usage_groups", "now": "2026-11-20T10:00:00+00:00", "account": {"id": "u1"},
    "period": {"window_start": "2026-11-01T00:00:00+00:00", "window_end": "2026-12-01T00:00:00+00:00",
               "previous_start": "2026-10-01T00:00:00+00:00"},
    "fields": ["usage_type", "usage_subtype", "workflow_id", "number"], "groups": [GROUP],
    "directory": {"workflows": {}, "agents": {}, "people": {"u1": {"name": "Ada"}}},
}
CHARGE = {
    "id": "ev_1", "created_at": "2026-11-19T09:00:00+00:00", "user_id": "u1", "organization_id": None,
    "usage_type": "api_usage", "usage_subtype": "voice/call", "quantity": 120.0, "unit_type": "seconds",
    "total_cost": 0.25, "user_resource": False, "k": "k1", "metadata": {"number": "+14155550132"},
}


def test_the_ledger_reads_its_groups_in_a_zone(api, client):
    route = api.get("/v1/usage/groups").respond(json=LEDGER)
    ledger = nc.Usage.ledger(tz="Asia/Kolkata")
    assert route.calls.last.request.url.params["tz"] == "Asia/Kolkata"
    assert "noclick-user" not in route.calls.last.request.headers
    assert ledger.period_start == datetime.datetime(2026, 11, 1, tzinfo=UTC)
    assert ledger.previous_start == datetime.datetime(2026, 10, 1, tzinfo=UTC)
    [group] = ledger.groups
    assert (group.key, group.current, group.day, group.subtype, group.own_resource, group.charges, group.usd) == (
        "k1", True, "2026-11-19", "voice/call", False, 2, 0.5)
    assert group.fields == {"usage_type": "api_usage", "usage_subtype": "voice/call", "workflow_id": None,
                            "number": "+14155550132"}
    assert ledger.directory["people"]["u1"] == {"name": "Ada"}


def test_charges_are_narrowed_and_paged(api, client):
    route = api.post("/v1/usage/charges").respond(json={"object": "usage_charges", "rows": [CHARGE], "runs": {},
                                                        "next": "2026-11-19T09:00:00+00:00|ev_1"})
    page = nc.Usage.charges(keys=["k1"], day="2026-11-19", tz="UTC", limit=1)
    assert json.loads(route.calls.last.request.content) == {"keys": ["k1"], "day": "2026-11-19", "tz": "UTC",
                                                            "limit": 1}
    [charge] = page.charges
    assert (charge.id, charge.key, charge.usd, charge.metadata) == ("ev_1", "k1", 0.25, {"number": "+14155550132"})
    assert charge.at == datetime.datetime(2026, 11, 19, 9, tzinfo=UTC)
    assert page.next == "2026-11-19T09:00:00+00:00|ev_1"
    nc.Usage.charges(from_=datetime.datetime(2026, 11, 1, tzinfo=UTC), to="2026-12-01T00:00:00Z", cursor=page.next)
    assert json.loads(route.calls.last.request.content) == {
        "start": "2026-11-01T00:00:00+00:00", "end": "2026-12-01T00:00:00Z", "cursor": page.next}


def test_the_money_behind_it_or_none(api, client):
    route = api.get("/v1/usage/billing").respond(json={"object": "usage_billing", "billing": {
        "plan": {"tier": "member", "included_usd": 10}, "balance": {"usd": -2.5, "has": True},
        "funds": {"usd": 20, "fee": 1, "count": 1}, "recurring": [{"id": "r1", "label": "+1 415 555 0132"}],
        "domains": [],
    }})
    money = nc.Usage.billing()
    assert (money.balance_usd, money.funds_usd, money.fees_usd, money.plan["included_usd"]) == (-2.5, 20, 1, 10)
    assert money.recurring[0]["id"] == "r1" and money.auto_top_up is None
    route.respond(json={"object": "usage_billing", "billing": None})
    assert nc.Usage.billing() is None


def test_credits_read_the_meters_pool_a_team_workspaces_by_its_id(api, client):
    route = api.get("/v1/usage/credits").respond(json={
        "object": "credit_usage", "used": 1.5, "limit": 4, "period": "day", "monthly_used": 3, "monthly_cap": 20,
        "topup_credits": 0, "effective_tier": "free", "is_org_credits": True, "organization_id": "org_1",
        "pool_user_id": "user_owner", "balance_usd": 2.5})
    meter = nc.Usage.credits(organization_id="org_1")
    assert route.calls.last.request.url.params["organization_id"] == "org_1"
    assert isinstance(meter, nc.UsageCredits)
    assert (meter.used, meter.limit, meter.period, meter.balance_usd, meter.pool_user_id, meter.is_org_credits) == (
        1.5, 4, "day", 2.5, "user_owner", True)
    nc.Usage.credits()
    assert "organization_id" not in route.calls.last.request.url.params

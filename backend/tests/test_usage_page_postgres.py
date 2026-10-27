"""The usage page's reads against real Postgres (repositories/usage_page.py,
wss/handlers/usage_page_handler.py), where nobody is billed: the period is the
UTC calendar month and the page shows what each thing cost.

These pin: the groups are the payer's rows split by window, UTC day and every
breakdown field, and their sums are the rows'; a group's key picks exactly its
rows out of the charges; charges page newest first by a cursor that neither
skips nor repeats a row; a day narrows them to that UTC day; a charge's run and
the names of what it was for come with it; and someone else's rows never do.
Rows are inserted the way the trackers write them (with only the columns every
schema has)."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from repositories.usage_page import ChargesCursor, UsagePageRepo
from utils import capabilities
from wss.handlers import usage_page_handler
from wss.handlers.usage_page_handler import calendar_period, charges_page, page

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 16, 15, 20, tzinfo=timezone.utc)


@pytest.fixture
async def db(postgres_db, postgres_container, monkeypatch):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=4, init=setup_asyncpg_codecs,
    )
    monkeypatch.setattr("utils.database_pool._native_pool", pool)
    monkeypatch.setattr("utils.database_pool._native_pool_loop", None)
    monkeypatch.setattr(usage_page_handler, "billing_now", lambda: NOW)
    # Where nobody is billed: no USAGE_BILLING, whatever this suite's deployment registered.
    monkeypatch.setattr(capabilities, "_providers", {k: v for k, v in capabilities._providers.items() if k != capabilities.USAGE_BILLING})
    try:
        yield pool
    finally:
        await pool.close()


async def account(pool, name="Ada Lovelace") -> str:
    return str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, $2::text::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:10]}@example.com", json.dumps({"full_name": name})))


async def workflow(pool, owner, name, nodes) -> str:
    graph = {"nodes": [{"id": n, "type": "automation-agent", "data": {"label": label, "config": {"label": label}}} for n, label in nodes], "edges": []}
    return str(await pool.fetchval("INSERT INTO workflows (owner_id, name, workflow) VALUES ($1::uuid, $2, $3::text::jsonb) RETURNING id",
                                   owner, name, json.dumps(graph)))


async def run(pool, owner, workflow_id, at) -> str:
    return str(await pool.fetchval(
        """INSERT INTO workflow_executions (workflow_id, user_id, status, started_at, finished_at, nodes_executed, trigger_source)
           VALUES ($1::uuid, $2::uuid, 'completed', $3, $4, 2, 'webhook') RETURNING id""",
        workflow_id, owner, at, at + timedelta(seconds=30)))


async def charge(pool, user_id, at, usd, subtype="openrouter/anthropic/claude-sonnet-4.6", *, usage_type="ai_usage",
                 unit="tokens", quantity=1000, **metadata) -> str:
    return str(await pool.fetchval(
        """INSERT INTO user_usage_events (user_id, total_cost, usage_type, usage_subtype, quantity, unit_type,
               user_resource, metadata, created_at)
           VALUES ($1::uuid, $2, $3, $4, $5, $6, false, $7::text::jsonb, $8) RETURNING id""",
        user_id, usd, usage_type, subtype, quantity, unit, json.dumps(metadata), at))


def total(rows):
    return round(sum(r["total_cost"] for r in rows), 6)


async def test_the_page_groups_a_payers_charges_in_the_calendar_month(db):
    me, someone = await account(db), await account(db, "Someone Else")
    wf = await workflow(db, me, "Inbox triage", [("agent-1", "Support agent")])
    oct3 = datetime(2026, 10, 3, 9, tzinfo=timezone.utc)
    execution = await run(db, me, wf, oct3)
    await charge(db, me, oct3, 0.40, workflow_id=wf, node_id="agent-1", execution_id=execution, prompt_tokens=900, completion_tokens=100)
    await charge(db, me, oct3 + timedelta(hours=2), 0.10, workflow_id=wf, node_id="agent-1")
    await charge(db, me, datetime(2026, 10, 15, 22, tzinfo=timezone.utc), 0.25, "voice/call", usage_type="api_usage",
                 unit="seconds", quantity=120, number="+14155550132", direction="inbound", channel="number")
    await charge(db, me, datetime(2026, 9, 20, tzinfo=timezone.utc), 1.00)        # last month
    await charge(db, me, datetime(2026, 8, 20, tzinfo=timezone.utc), 5.00)        # before it: not read
    await charge(db, someone, oct3, 9.99)                                         # someone else's

    out = await page(me)
    assert out["billing"] is None
    assert out["period"] == {"window_start": "2026-10-01T00:00:00+00:00", "window_end": "2026-11-01T00:00:00+00:00",
                             "previous_start": "2026-09-01T00:00:00+00:00"}
    current = [g for g in out["groups"] if g["current"]]
    assert total(current) == 0.75 and sum(g["n"] for g in current) == 3
    assert total([g for g in out["groups"] if not g["current"]]) == 1.0
    # The two model calls share a day, a model, an automation and an agent (a run isn't a breakdown field): one group.
    [model] = [g for g in current if g["usage_type"] == "ai_usage"]
    assert (model["day"], model["workflow_id"], model["node_id"], model["n"], model["prompt_tokens"]) == ("2026-10-03", wf, "agent-1", 2, 900)
    assert round(model["total_cost"], 6) == 0.5
    call = next(g for g in current if g["usage_subtype"] == "voice/call")
    assert (call["number"], call["channel"], call["unit_type"], call["quantity"]) == ("+14155550132", "number", "seconds", 120.0)
    # Names for what the charges were for, the payer's own.
    assert out["directory"]["workflows"] == {wf: {"name": "Inbox triage"}}
    assert out["directory"]["agents"] == {f"{wf}:agent-1": {"name": "Support agent"}}
    assert out["directory"]["people"] == {me: {"name": "Ada Lovelace"}}
    # The first page: this period's charges, newest first, with the run one of them belongs to.
    rows = out["charges"]["rows"]
    assert [r["total_cost"] for r in rows] == [0.25, 0.10, 0.40] and out["charges"]["next"] is None
    assert rows[2]["metadata"]["execution_id"] == execution
    assert out["charges"]["runs"][execution]["workflow"] == {"id": wf, "name": "Inbox triage"}
    assert rows[0]["metadata"] == {"number": "+14155550132", "direction": "inbound", "channel": "number"}


async def test_charges_page_by_cursor_and_narrow_by_key_and_day(db):
    me = await account(db)
    start = datetime(2026, 10, 2, tzinfo=timezone.utc)
    ids = []
    for i in range(7):
        ids.append(await charge(db, me, start + timedelta(hours=i * 7), 0.01 * (i + 1),
                                "exa/search_api" if i % 2 else "openrouter/openai/gpt-5.5",
                                usage_type="api_usage" if i % 2 else "ai_usage"))
    period = calendar_period(NOW)
    window = dict(start=period["window_start"], end=period["window_end"])
    seen, cursor = [], None
    while True:
        got = await charges_page(me, **window, cursor=cursor and ChargesCursor.decode(cursor), limit=3)
        seen += [r["id"] for r in got["rows"]]
        cursor = got["next"]
        if not cursor:
            break
    assert seen == list(reversed(ids))  # newest first, nothing skipped or repeated

    groups = (await page(me))["groups"]
    tools = {g["k"] for g in groups if g["usage_subtype"] == "exa/search_api"}
    narrowed = await charges_page(me, **window, keys=sorted(tools), limit=50)
    assert [r["usage_subtype"] for r in narrowed["rows"]] == ["exa/search_api"] * 3
    assert all(r["k"] in tools for r in narrowed["rows"])
    assert (await charges_page(me, **window, keys=[], limit=50))["rows"] == []
    day = await charges_page(me, **window, day="2026-10-03", limit=50)
    assert {r["created_at"][:10] for r in day["rows"]} == {"2026-10-03"} and len(day["rows"]) == 3


async def test_charges_recorded_in_the_same_instant_page_without_a_gap_or_a_repeat(db):
    # A site's hourly reading records its charges in one statement, so they share a created_at to the microsecond:
    # the cursor's id breaks the tie exactly as the page's order does, narrowed or not.
    me = await account(db)
    reading = datetime(2026, 10, 9, 10, 0, 1, 123456, tzinfo=timezone.utc)
    ids = [await charge(db, me, reading, 0.001 * (i + 1), "apps/hosting" if i % 2 else "apps/releases",
                        usage_type="api_usage") for i in range(7)]
    ids += [await charge(db, me, reading + timedelta(microseconds=1), 0.01, "apps/hosting", usage_type="api_usage"),
            await charge(db, me, reading - timedelta(microseconds=1), 0.02, "apps/hosting", usage_type="api_usage")]
    period = calendar_period(NOW)
    window = dict(start=period["window_start"], end=period["window_end"])
    rows = await db.fetch("SELECT id, created_at, usage_subtype FROM user_usage_events WHERE user_id = $1::uuid", me)
    newest_first = sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)
    hosting = {g["k"] for g in (await page(me))["groups"] if g["usage_subtype"] == "apps/hosting"}

    for keys, expected in ((None, newest_first), (sorted(hosting), [r for r in newest_first if r["usage_subtype"] == "apps/hosting"])):
        for limit in (1, 2, 3, 4):
            seen, cursor = [], None
            while True:
                got = await charges_page(me, **window, keys=keys, cursor=cursor and ChargesCursor.decode(cursor), limit=limit)
                seen += [r["id"] for r in got["rows"]]
                cursor = got["next"]
                if not cursor:
                    break
            assert seen == [str(r["id"]) for r in expected], (keys, limit)
    assert sorted(seen) == sorted(set(seen)) and len(ids) == 9


async def test_only_an_emails_from_is_a_sender(db):
    """An app's metered storage names the stretch it covers (``from``/``to``): the day's beats are one group, not one
    each. An email's ``from`` is who sent it, and splits its charges by sender."""
    me = await account(db)
    project = str(uuid.uuid4())
    beat = datetime(2026, 10, 9, 8, tzinfo=timezone.utc)
    for i in range(3):
        at = beat + timedelta(minutes=50 * i)
        await charge(db, me, at, 0.001, "apps/releases", usage_type="api_usage", unit="gb_hours", project_id=project,
                     **{"from": (at - timedelta(minutes=50)).isoformat(), "to": at.isoformat()})
    for sender in ("agent-reply-a@noclick.app", "agent-reply-b@noclick.app"):
        await charge(db, me, beat, 0.0004, "email/agent_update", usage_type="api_usage", unit="emails", **{"from": sender})

    groups = [g for g in (await page(me))["groups"] if g["current"]]
    [storage] = [g for g in groups if g["usage_subtype"] == "apps/releases"]
    assert (storage["n"], storage["project_id"], storage["sender"]) == (3, project, None)
    emails = [g for g in groups if g["usage_subtype"] == "email/agent_update"]
    assert sorted(g["sender"] for g in emails) == ["agent-reply-a@noclick.app", "agent-reply-b@noclick.app"]
    # The charges still say what stretch they covered.
    rows = (await charges_page(me, start=beat, end=beat + timedelta(days=1), keys=[storage["k"]]))["rows"]
    assert len(rows) == 3 and all(r["metadata"]["from"] < r["metadata"]["to"] for r in rows)


async def test_a_sites_traffic_keeps_the_requests_it_counted(db):
    """The ledger counts a site's traffic in millions of requests, so a reading's line keeps the count beside it."""
    me = await account(db)
    at = datetime(2026, 10, 9, 8, tzinfo=timezone.utc)
    await charge(db, me, at, 0.0011, "apps/hosting", usage_type="api_usage", unit="million_requests", quantity=0.0012,
                 project_id=str(uuid.uuid4()), requests=1234, **{"from": (at - timedelta(hours=1)).isoformat(), "to": at.isoformat()})
    [row] = (await charges_page(me, start=at - timedelta(days=1), end=at + timedelta(days=1)))["rows"]
    assert row["metadata"]["requests"] == 1234


async def test_a_run_from_someone_elses_workflow_is_not_named(db):
    me, someone = await account(db), await account(db)
    theirs = await workflow(db, someone, "Not mine", [("agent-1", "Theirs")])
    execution = await run(db, someone, theirs, datetime(2026, 10, 5, tzinfo=timezone.utc))
    await charge(db, me, datetime(2026, 10, 5, 1, tzinfo=timezone.utc), 0.2, execution_id=execution)
    out = await page(me)
    assert out["charges"]["runs"] == {}


async def test_a_workspace_members_run_comes_with_its_charge_on_the_owners_page(db):
    """Owner Pays bills the workspace's owner for a member's run in a member's automation: the charge's run is
    the owner's to open too."""
    owner, teammate = await account(db, "Owner"), await account(db, "Teammate")
    org = str(await db.fetchval(
        "INSERT INTO organizations (name, slug, is_personal_workspace) VALUES ('Fernway', $1, false) RETURNING id",
        f"fernway-{uuid.uuid4().hex[:6]}"))
    await db.execute("INSERT INTO organization_members (organization_id, user_id, role) VALUES ($1::uuid, $2::uuid, 'owner'), "
                     "($1::uuid, $3::uuid, 'member')", org, owner, teammate)
    wf = await workflow(db, teammate, "Teammate's triage", [("agent-1", "Triage agent")])
    await db.execute("UPDATE workflows SET organization_id = $2::uuid WHERE id = $1::uuid", wf, org)
    at = datetime(2026, 10, 5, tzinfo=timezone.utc)
    execution = await run(db, teammate, wf, at)
    await charge(db, owner, at, 0.3, workflow_id=wf, node_id="agent-1", execution_id=execution, actual_user_id=teammate)

    out = await page(owner)
    assert out["charges"]["runs"][execution]["workflow"] == {"id": wf, "name": "Teammate's triage"}


async def test_the_repository_ignores_what_isnt_an_id(db):
    me = await account(db)
    repo = UsagePageRepo(db)
    assert await repo.runs(user_id=me, execution_ids=["not-a-uuid", ""]) == []
    names = await repo.names(workflow_ids=["nope"], agents=[], people=["also-not"])
    assert names == {"workflows": {}, "agents": {}, "people": {}}

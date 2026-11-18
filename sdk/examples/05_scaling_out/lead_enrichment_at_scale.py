# ---
# description: Research and score 10,000 leads with a queue of agents that search the web on NoClick's key, keep every result in one database and send the best to HubSpot, with progress, throughput, retries and cost while it runs.
# card_title: Enrich 10,000 leads with agents
# card_line: Researched, scored, sent to HubSpot.
# mark: automation-hubspot
# cmd: ["python", "05_scaling_out/lead_enrichment_at_scale.py"]
# env: ["NOCLICK_API_KEY", "LEADS_CSV"]
# deps: []
# ---

# # Enrich 10,000 leads with a queue of agents
#
# Marketing hands sales a spreadsheet of 10,000 people who signed up at a trade show. Sales has
# time for three hundred calls. Which three hundred? Each company takes a few minutes of real
# research: find the right company behind the domain, see what it does and how big it is, look for
# a reason it would buy now. That's judgment, which an agent does well, done 10,000 times, which
# is a job for a queue.
#
# In this example every lead goes on a [queue](/docs/guide/queues). Ten agents take them ten at a
# time as they come, research each with Exa's web search on NoClick's key (no account to
# connect), score it against your ideal customer and save the result in a
# [database](/docs/guide/databases). Nothing runs on your machine while it works. Run the script
# again whenever you like: it shows how far along the job is, how fast it's going, what failed and
# what it has cost, and it sends the leads that scored highest to HubSpot.
#
# `LEADS_CSV` is your spreadsheet, as CSV with the columns `company`, `domain`, `contact_name`,
# `contact_email` and `title`.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# export LEADS_CSV=tradeshow-leads.csv
# python 05_scaling_out/lead_enrichment_at_scale.py
# ```

import csv
import json
import os
import sys

import noclick

LEADS_CSV = os.environ["LEADS_CSV"]
HOT_SCORE = 80  # leads at or above this go to HubSpot
PERSONAL_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "proton.me"}
RESEARCHERS = 10  # agents on the queue: each takes one turn at a time

# ## Who you're looking for
#
# The scoring rubric is written for the model, in points, so a score means the same thing on the
# first lead and the ten-thousandth. Here the product is shift-scheduling software, so the question
# for each company is whether its people work shifts and whether it's the right size.

RESEARCHER = """You research B2B leads for Tandem, which sells shift-scheduling software to businesses
whose staff work hourly shifts: restaurants, clinics, retail, warehouses, hotels.

Each turn you get a JSON list of leads, each with a domain and a company name. For each one:
1. Search for it with exa.search, the domain first. Work out what the company does, the country it's
   based in, about how many employees it has, and whether most of them work shifts. Use at most three
   searches. The company behind the domain is the one that matters, not a namesake.
2. Score its fit from 0 to 100:
   - 40 points if most of its staff work hourly shifts
   - 25 points for 20 to 2,000 employees
   - 15 points for the US, Canada or the UK
   - 20 points for a reason to buy this year: hiring many hourly roles, opening locations, a new head
     of operations, or complaints about scheduling
3. Save it with the upsert tool: domain, industry, employees (a number, or null), country,
   shift_workers (true, false or null), score, reason (one sentence a salesperson can read aloud)
   and sources (the URLs you used).
If you can't tell which company it is, save it with score 0 and reason "Couldn't identify the company".
Save every lead in the list, then reply "done"."""

# ## Where the results go
#
# Results need to be ranked, joined back to the contact, counted while the job runs and read by the
# step that fills the CRM, and that is SQL. The database has two tables: `leads` is what you
# imported, and `enriched` is what the agents found. They write only to `enriched`, one row
# per domain, so a lead researched twice (a queue delivers at least once) is still one row.
#
# `migrate` applies the schema the first time and does nothing after that.

SCHEMA = {
    "0001_leads.sql": """
create table leads (
    domain text primary key,
    company text not null,
    contact_name text,
    contact_email text,
    title text,
    queued_at text,
    pushed_at text
);
create table enriched (
    domain text primary key,
    industry text,
    employees integer,
    country text,
    shift_workers integer,
    score integer not null check (score between 0 and 100),
    reason text not null,
    sources text,
    researched_at text not null default (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
create index enriched_by_score on enriched (score);
create index enriched_by_time on enriched (researched_at);
""",
}


def results_db() -> noclick.Database:
    db = noclick.Database.from_name("leads", create_if_missing=True)
    db.migrate(SCHEMA)
    return db


# ## The queue and the agents that work it
#
# One message per lead. A queue hands messages out and takes them back: a turn that finishes
# acknowledges its leads, a turn that fails puts them back for another try, and a lead that fails
# three times becomes a dead letter you can look at, instead of a gap in the results nobody notices.
#
# Each researcher is an [agent](/docs/guide/agents) with an `OnQueue`
# [trigger](/docs/guide/triggers#wake-it-from-a-queue), so each batch of ten waiting leads becomes
# one of its turns, with no worker process of yours. Ten a turn keeps the instructions from being
# paid for on every lead. An agent takes one turn at a time, so more agents on the one queue is
# what makes the job faster: 10,000 leads one turn at a time would take most of a day, and ten
# researchers take a tenth of that. They run a fast, cheap model, which is plenty for search and a
# rubric.
#
# `budget_usd_per_month` is the most each researcher can cost, $150 for the whole job, whatever goes
# wrong. When one's is spent, its trigger pauses rather than failing turns: its leads wait on the
# queue with their attempts unchanged, and the work carries on by itself once there's budget again.
#
# Their tools are Exa's search and a single write. `db.only("upsert").bind(table="enriched")` is a
# tool that writes one row of `enriched` by its primary key, with the table's columns as its
# parameters, so the model fills in a form rather than writing SQL. It can't read your leads table,
# change another row's contact, or drop anything.


def lead_queue() -> noclick.Queue:
    return noclick.Queue.from_name("lead-research", create_if_missing=True, max_attempts=3)


def hire_researchers(db: noclick.Database, queue: noclick.Queue) -> list[noclick.Agent]:
    return [
        noclick.Agent.from_name(
            f"lead-researcher-{n}",
            create_if_missing=True,
            model="openrouter/google/gemini-2.5-flash",
            instructions=RESEARCHER,
            tools=[
                "exa.search",
                db.only("upsert").bind(table="enriched"),
            ],
            triggers=[
                noclick.OnQueue(queue, batch_size=10, message="Research and score these leads."),
            ],
            budget_usd_per_month=150 / RESEARCHERS,
        )
        for n in range(1, RESEARCHERS + 1)
    ]


# ## Import the spreadsheet and fan it out
#
# The CSV goes into `leads`, one row per company domain; a lead with only a personal email address
# has no company to research and is skipped. `on conflict do nothing` makes the import safe to run
# again with the same file, or a longer one.
#
# Then every lead that hasn't been queued goes on the queue, a hundred at a time, and is marked
# queued once the queue has it. If the script stops between the two, the next run queues those
# leads again, which costs a second look at up to a hundred companies and loses nothing.


def read_leads(path: str) -> list[dict]:
    leads: dict[str, dict] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            email = (row.get("contact_email") or "").strip().lower()
            domain = (row.get("domain") or email.partition("@")[2]).strip().lower()
            domain = domain.removeprefix("https://").removeprefix("http://").removeprefix("www.").strip("/")
            if domain and domain not in PERSONAL_MAIL:
                leads.setdefault(domain, {
                    "domain": domain,
                    "company": (row.get("company") or domain).strip(),
                    "contact_name": (row.get("contact_name") or "").strip(),
                    "contact_email": email or None,
                    "title": (row.get("title") or "").strip(),
                })
    return list(leads.values())


def import_leads(db: noclick.Database, leads: list[dict]) -> None:
    columns = ("domain", "company", "contact_name", "contact_email", "title")
    for start in range(0, len(leads), 500):
        chunk = leads[start:start + 500]
        db.execute(
            f"insert into leads ({', '.join(columns)}) values "
            + ", ".join(["(?, ?, ?, ?, ?)"] * len(chunk))
            + " on conflict (domain) do nothing",
            [lead[column] for lead in chunk for column in columns],
        )


def fan_out(db: noclick.Database, queue: noclick.Queue) -> int:
    queued = 0
    while True:
        batch = db.query("select domain, company from leads where queued_at is null limit 100").rows
        if not batch:
            return queued
        queue.put_many(batch)
        db.execute(
            "update leads set queued_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') where domain in ("
            + ", ".join(["?"] * len(batch)) + ")",
            [lead["domain"] for lead in batch],
        )
        queued += len(batch)


# ## Watch it run
#
# Every number here comes from where it already is. Progress and throughput are counts in the
# database, the queue knows what's waiting, in flight and dead, each trigger says whether it's
# paused for money, and the agents' budgets know what they have spent.
#
# Dead letters are the leads that failed three times, each with the error of its last try. Fix what
# made them fail, then `python 05_scaling_out/lead_enrichment_at_scale.py retry` puts them back.


def progress(db: noclick.Database, queue: noclick.Queue, researchers: list[noclick.Agent]) -> None:
    counts = db.query(
        """select count(*) as total,
                  count(e.domain) as researched,
                  coalesce(sum(e.score >= :hot), 0) as hot,
                  coalesce(sum(e.researched_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-10 minutes')), 0) as recent
           from leads l left join enriched e using (domain)""",
        {"hot": HOT_SCORE},
    ).rows[0]
    queue.refresh()
    print(f"\n{counts['researched']:,} of {counts['total']:,} leads researched, {counts['hot']:,} scored {HOT_SCORE} or more")
    print(f"Queue: {queue.depth:,} waiting, {queue.in_flight:,} in flight, {queue.dead_letter_count:,} failed three times")

    per_minute = counts["recent"] / 10
    remaining = counts["total"] - counts["researched"]
    if per_minute and remaining:
        print(f"Doing {per_minute:.0f} leads a minute: about {remaining / per_minute:.0f} minutes to go")
    history = queue.depth_history(hours=6)
    print("Waiting, every 15 minutes:", " ".join(str(point.depth) for point in history))

    retried = [message for message in queue.peek(limit=100) if message.attempts > 1]
    print(f"{len(retried)} of the oldest 100 in the queue are on a second or third try")
    for letter in queue.dead_letters(limit=5):
        print("  failed:", letter.body["domain"], letter.last_error)

    for researcher in researchers:
        for trigger in researcher.triggers():
            if trigger.status == "error":
                print(f"{researcher.name} paused, leads waiting: {trigger.error}")
    ids = {researcher.id for researcher in researchers}
    budgets = [budget for budget in noclick.Usage.limits().agents if budget.id in ids]
    spent, budget = sum(b.spent for b in budgets), sum(b.budget or 0 for b in budgets)
    per_lead = spent / max(counts["researched"], 1)
    print(f"Spent ${spent:.2f} of the ${budget:.0f} budget this month, ${per_lead:.4f} a lead")


# ## Send the best to HubSpot
#
# Leads that scored high enough go to HubSpot as contacts, with the score and the reason on the
# record so the salesperson knows why they're calling. `batch_upsert_records` writes a hundred at a
# time and matches contacts by email, so a lead sent twice updates the contact it made the first
# time rather than making another.
#
# Add two contact properties in HubSpot once, `fit_score` (a number) and `fit_reason` (text).
# HubSpot is a [connection](/docs/guide/connections): the first run prints the link to connect it.


def connect_crm() -> noclick.Connection:
    crm = noclick.Connection.from_name(
        "crm", integration="hubspot", create_if_missing=True, reason="to add the best trade show leads as contacts",
    )
    if not crm.connected:
        print("Connect HubSpot:", crm.connect_url)
        crm.wait()
    return crm


def push_best(db: noclick.Database, crm: noclick.Connection) -> int:
    pushed = 0
    while True:
        rows = db.query(
            """select l.domain, l.company, l.contact_name, l.contact_email, l.title, e.score, e.reason
               from leads l join enriched e using (domain)
               where e.score >= ? and l.pushed_at is null and l.contact_email is not null
               order by e.score desc limit 100""",
            [HOT_SCORE],
        ).rows
        if not rows:
            return pushed
        inputs = []
        for row in rows:
            first, _, last = row["contact_name"].partition(" ")
            inputs.append({"idProperty": "email", "id": row["contact_email"], "properties": {
                "email": row["contact_email"], "firstname": first, "lastname": last, "company": row["company"],
                "website": row["domain"], "jobtitle": row["title"], "hs_lead_status": "NEW",
                "fit_score": row["score"], "fit_reason": row["reason"],
            }})
        crm.run("batch_upsert_records", {"object_type": "contacts", "inputs": json.dumps(inputs)})
        db.execute(
            "update leads set pushed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') where domain in ("
            + ", ".join(["?"] * len(rows)) + ")",
            [row["domain"] for row in rows],
        )
        pushed += len(rows)


# ## Stop, retry, carry on
#
# `stop` pauses the researchers and empties the queue, and marks the leads they hadn't reached as not
# queued, so the next plain run queues them again and resumes the researchers (turns already under
# way finish, so a few leads may be looked at twice). `retry` puts the dead
# letters back on the queue once you've fixed what made them fail. The database keeps every result
# until you delete it (`db.export()` gives you a SQL dump to keep first).


def stop(db: noclick.Database, queue: noclick.Queue, researchers: list[noclick.Agent]) -> None:
    for researcher in researchers:
        researcher.pause()
    queue.clear()
    db.execute("update leads set queued_at = null where domain not in (select domain from enriched)")


def retry(queue: noclick.Queue) -> None:
    for letter in queue.dead_letters():
        letter.retry()


def main() -> None:
    db = results_db()
    queue = lead_queue()
    researchers = hire_researchers(db, queue)
    if sys.argv[1:] == ["stop"]:
        stop(db, queue, researchers)
        return
    if sys.argv[1:] == ["retry"]:
        retry(queue)
    for researcher in researchers:
        if researcher.paused:
            researcher.resume()
    leads = read_leads(LEADS_CSV)
    import_leads(db, leads)
    print(f"{len(leads):,} companies in {LEADS_CSV}; queued {fan_out(db, queue):,} new ones")
    progress(db, queue, researchers)
    print(f"Sent {push_best(db, connect_crm()):,} leads to HubSpot")


if __name__ == "__main__":
    main()

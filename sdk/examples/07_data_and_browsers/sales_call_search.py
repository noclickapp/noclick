# ---
# description: Turn a folder of sales-call recordings into something you can ask, answered with quotes, timestamps and a link to the moment.
# card_title: Ask your sales calls anything
# card_line: Quotes and timestamps from recordings.
# mark: audio-lines
# cmd: ["python", "07_data_and_browsers/sales_call_search.py"]
# env: ["NOCLICK_API_KEY", "CALLS_DIR"]
# deps: []
# featured: true
# ---

# # Ask your sales calls anything
#
# Your team records its sales calls. Somewhere in two hundred hours of audio, a handful of customers
# asked about single sign-on, and your product manager wants to know who, what exactly they asked,
# and when. This example builds what answers that:
#
# > **Which customers asked about SSO last month?**
# >
# > Two did. **Acme** asked whether SSO works with Okta: "we can't roll it out to the team without
# > it" (14 September, 12:41, [listen](#)). **Globex** asked if SAML is on the Team plan (22
# > September, 03:05, [listen](#)).
#
# Each part does one job:
#
# - A **bucket** holds the recordings. A one-hour call is around 60 MB; you upload it once, and
#   transcription reads it from the bucket by a signed link, so nothing downloads it again.
# - A **queue** hands recordings to workers. Transcribing hours of audio takes a while: a worker
#   that crashes has its recording delivered again, a file that can't be transcribed ends up as a
#   dead letter with the reason, and you can run workers on as many machines as you like.
# - A Postgres **database** keeps each call's transcript in passages of about a minute, with an
#   embedding for search by meaning and a full-text index for exact words, side by side.
# - An **agent** turns a question into SQL, reads the passages it finds, and answers with quotes.
#   Your code turns its citations into links that open the recording at that second.
#
# Put your recordings in a folder, named `date_customer_rep` (`2026-09-14_acme_dana.mp3`), and
# point `CALLS_DIR` at it. Anything after the script name is your question.
#
# ```bash
# export CALLS_DIR=~/sales-calls
# python 07_data_and_browsers/sales_call_search.py
# python 07_data_and_browsers/sales_call_search.py "What did customers say about our pricing in August?"
# ```

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import noclick

EMBEDDING_MODEL = "openrouter/openai/text-embedding-3-small"
PASSAGE_SECONDS = 60
WORKERS = 4
AUDIO = {".mp3", ".m4a", ".wav", ".ogg", ".webm", ".mp4"}

recordings = noclick.Bucket.from_name("sales-calls", create_if_missing=True)
jobs = noclick.Queue.from_name("sales-call-indexing", create_if_missing=True, max_attempts=3)
calls_db = noclick.Database.from_name("sales-calls", create_if_missing=True, engine="postgres")

# ## The database
#
# Two tables: `calls`, one row per recording, and `passages`, its transcript in pieces of about a
# minute. A passage keeps where it starts in the call, the text with who said what, its embedding
# as a `halfvec` (half the memory of `vector`, with little effect on search quality), and a
# generated full-text column. Search by meaning finds "we can't let everyone share one password";
# full text finds "SSO", "SAML" and "Okta" exactly. Postgres holds both, so one query can use
# either, and filter by customer and date too.
#
# `migrate` applies the migrations the database hasn't run yet, so this runs on every start.
# `etag` records which version of each recording was indexed: a replaced file gets indexed again.

MIGRATIONS = {
    "0001_calls.sql": """
create table calls (
    id text primary key,
    etag text not null,
    customer text,
    rep text,
    recorded_on date,
    duration_s real,
    cost_usd real,
    indexed_at timestamptz not null default now()
);

create table passages (
    call_id text not null references calls (id) on delete cascade,
    position integer not null,
    start_s real not null,
    end_s real not null,
    text text not null,
    embedding halfvec(1536) not null,
    search tsvector generated always as (to_tsvector('english', text)) stored,
    primary key (call_id, position)
);

create index passages_embedding on passages using hnsw (embedding halfvec_cosine_ops);
create index passages_search on passages using gin (search);
create index calls_recorded_on on calls (recorded_on);
""",
}

# ## Upload recordings
#
# Each recording goes into the bucket under `calls/<month>/`, with the customer, the rep and the
# date as metadata for the workers to read. A file that's already there at the same size is
# skipped, so running this again uploads only what's new. One `put` carries up to 100 MB; a longer
# recording goes up through `recordings.signed_url(key, method="PUT")`, a link that takes up to
# 5 GB.
#
# If your call recorder can export to S3, it can write to the bucket directly with keys from
# `recordings.s3_credentials()`, and the next run indexes what it wrote.


def upload(folder: str) -> int:
    uploaded = 0
    for path in sorted(Path(folder).expanduser().iterdir()):
        named = re.fullmatch(r"(\d{4}-\d{2}-\d{2})_([^_]+)_(.+)", path.stem)
        if path.suffix.lower() not in AUDIO or not named:
            continue
        recorded_on, customer, rep = named.groups()
        key = f"calls/{recorded_on[:7]}/{path.name}"
        try:
            if recordings.head(key).size == path.stat().st_size:
                continue
        except noclick.NotFound:
            pass
        with open(path, "rb") as f:
            recordings.put(key, f, metadata={
                "customer": customer.replace("-", " ").title(), "rep": rep.title(), "recorded_on": recorded_on,
            })
        uploaded += 1
    return uploaded


# ## Queue what isn't indexed yet
#
# A recording needs indexing when the database has no row for it, or has one for an older version
# of the file. Each gets a message on the queue, a hundred to a call.
#
# Delivery is at least once, so indexing is safe to repeat: a worker first checks the database for
# this version of the file, and a call's rows are replaced in one transaction.


def queue_unindexed() -> int:
    indexed = {row["id"]: row["etag"] for row in calls_db.query("select id, etag from calls")}
    keys = [obj.key for obj in recordings.objects(prefix="calls/") if indexed.get(obj.key) != obj.etag]
    for start in range(0, len(keys), 100):
        jobs.put_many([{"key": key} for key in keys[start:start + 100]])
    return len(keys)


# ## Index one recording
#
# Transcription takes the recording's signed link, so NoClick fetches the audio straight from the
# bucket (up to 200 MB, or two hours). Knowing who said each thing matters here: "which customers
# asked about SSO" is about the customer's words, not the rep's pitch. `speakers=True` tells the
# voices apart and labels each segment's `speaker` (`speaker_1`, `speaker_2`, in the order they
# first speak), which costs a little more per minute.
#
# The segments are grouped into passages of about a minute, each line stamped with its time and
# speaker. Every passage is embedded with the call's customer and date in front of it, so a search
# for "Acme's security questions" lands on Acme's calls. The call's rows go in with one `batch`,
# which is one transaction: a reader never sees half a call.


def clock(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def to_passages(segments: list[noclick.TranscriptSegment]) -> list[dict]:
    groups, current = [], []
    for segment in segments:
        current.append(segment)
        if segment.end_s - current[0].start_s >= PASSAGE_SECONDS:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return [
        {
            "start_s": group[0].start_s,
            "end_s": group[-1].end_s,
            "text": "\n".join(f"[{clock(s.start_s)}] {s.speaker}: {s.text.strip()}" for s in group),
        }
        for group in groups
    ]


def index_call(key: str) -> str:
    info = recordings.head(key)
    done = calls_db.query("select etag from calls where id = ?", [key]).rows
    if done and done[0]["etag"] == info.etag:
        return f"{key} is already indexed"
    customer, rep, recorded_on = (info.metadata.get(k) for k in ("customer", "rep", "recorded_on"))

    words = noclick.AI.transcribe(recordings.signed_url(key, expires_in=3600), speakers=True)
    passages = to_passages(words.segments)
    context = f"Sales call with {customer} on {recorded_on}, rep {rep}."
    embedded = noclick.AI.embed([f"{context}\n{p['text']}" for p in passages], model=EMBEDDING_MODEL)

    statements = [
        ("delete from calls where id = ?", [key]),
        (
            "insert into calls (id, etag, customer, rep, recorded_on, duration_s, cost_usd) "
            "values (?, ?, ?, ?, cast(? as date), ?, ?)",
            [key, info.etag, customer, rep, recorded_on, words.duration_s,
             (words.cost_usd or 0) + (embedded.cost_usd or 0)],
        ),
    ]
    rows = [
        [key, position, p["start_s"], p["end_s"], p["text"], vector]
        for position, (p, vector) in enumerate(zip(passages, embedded.vectors))
    ]
    for start in range(0, len(rows), 20):
        chunk = rows[start:start + 20]
        values = ", ".join(["(?, ?, ?, ?, ?, cast(? as halfvec))"] * len(chunk))
        statements.append((
            f"insert into passages (call_id, position, start_s, end_s, text, embedding) values {values}",
            [value for row in chunk for value in row],
        ))
    calls_db.batch(statements)
    return f"{key}: {len(passages)} passages, {clock(words.duration_s or 0)} of audio"


# ## Run the workers
#
# Each worker takes a message, indexes the recording and acknowledges it. The lease is half an
# hour, longer than a two-hour recording takes to transcribe, so nobody else gets the message while
# the work is going. A recording that fails goes back on the queue for another try a minute later,
# with the error: after three tries it becomes a dead letter that keeps the last one as
# `last_error`, so you can see why. Running out of money or reaching a spend cap isn't the
# recording's fault, so the worker hands the message back with `release`, which doesn't count as a
# try, and stops the run: the recording waits for the next run with all its tries left, instead of
# spending them against an empty balance and ending up a dead letter.
#
# Here the workers are threads in this script, and `iterate(stop_when_empty=True)` ends each one
# once nothing is waiting; a retry that's still a minute off waits for the next run. Without the
# queue, a recording that can't be transcribed would be tried again on every run with no record
# of why, and two machines indexing at once would transcribe, and pay for, the same call twice. For
# a big backlog, run `drain()` on more machines: each message goes to one worker at a time.


def work() -> None:
    for msg in jobs.iterate(lease_s=1800, stop_when_empty=True):
        try:
            print(index_call(msg.body["key"]))
        except (noclick.PaymentRequired, noclick.SpendCapExceeded):
            msg.release()
            raise
        except Exception as err:
            msg.nack(delay_s=60, error=f"{type(err).__name__}: {err}")
        else:
            msg.ack()


def drain() -> None:
    with ThreadPoolExecutor(WORKERS) as pool:
        for future in [pool.submit(work) for _ in range(WORKERS)]:
            future.result()


# ## Ask
#
# The agent has one tool: the database, limited to `query` (read-only SQL) and `schema`. It writes
# the SQL itself, filtering by date and customer, matching exact words with full text, and ranking
# passages by meaning. For that last part the question itself needs an embedding, made with the
# same model as the passages, inside the query:
# [`noclick.embed()`](/docs/guide/databases#embed-inside-sql) does that in SQL, is allowed in a
# read-only query, and is billed like `AI.embed`.
#
# Every turn starts with the date, so "last month" needs nothing from your code.
#
# It cites each quote as `call:<key>@<seconds>`. The model never handles a link that expires: your
# code swaps each citation for a signed link to the recording, valid for a week, with `#t=` so the
# browser's player starts at that second.

INSTRUCTIONS = f"""You answer questions about our recorded sales calls by querying the sales-calls
database with SQL. You can only read it.

Tables:
- calls: one row per recording. id, customer, rep (our salesperson), recorded_on (a date),
  duration_s.
- passages: each call's transcript in passages of about a minute. call_id, start_s and end_s
  (seconds into the call), text (lines of "[mm:ss] speaker: words", with speakers labelled per
  call; the rep is the one presenting our product), embedding, and search, a full-text index of
  text.

Searching:
- For words people say exactly (a product, a competitor, "SSO"), use full text and include the
  other ways people say it: where search @@ websearch_to_tsquery('english',
  'sso OR "single sign-on" OR saml OR okta').
- For ideas phrased many ways ("worried about the price"), rank by meaning:
  order by embedding <=> noclick.embed('worried about the price', '{EMBEDDING_MODEL}') limit 20.
- Filter dates on calls.recorded_on. "Last month" is the previous calendar month.
- Read the passages before you answer: a match isn't always the customer asking.

Answer with who asked, what they asked in their own words, and when. Quote the customer, not our
rep. After each quote, give the call's date, the time into the call, and a link written exactly
as [listen](call:<call id>@<seconds>), with the passage's start_s. If nothing matches, say so."""


def define_analyst() -> noclick.Agent:
    return noclick.Agent.from_name(
        "call-analyst",
        create_if_missing=True,
        instructions=INSTRUCTIONS,
        tools=[calls_db.only("query", "schema")],
    )


def link_moments(text: str) -> str:
    def link(match: re.Match) -> str:
        url = recordings.signed_url(match["key"], expires_in=7 * 86400)
        return f"({url}#t={match['seconds']})"

    return re.sub(r"\(call:(?P<key>[^@\s)]+)@(?P<seconds>\d+)\)", link, text)


def ask(analyst: noclick.Agent, question: str) -> str:
    return link_moments(analyst.message(question).text)


# The first `drain` finishes anything an earlier run left on the queue, so nothing gets queued
# twice; the second indexes what's new.


def main() -> None:
    calls_db.migrate(MIGRATIONS)
    if os.environ.get("CALLS_DIR"):
        print(f"Uploaded {upload(os.environ['CALLS_DIR'])} new recordings")
    drain()
    print(f"Queued {queue_unindexed()} recordings to index")
    drain()
    for letter in jobs.dead_letters():
        print(f"Couldn't index {letter.body['key']} after {letter.attempts} tries: {letter.last_error}")
    question = " ".join(sys.argv[1:]) or "Which customers asked about SSO last month?"
    print(f"\n{question}\n")
    print(ask(define_analyst(), question))


if __name__ == "__main__":
    main()

# ## What it costs
#
# Transcription is charged by the minute of audio, and embeddings by the token; each call's total
# is in its `cost_usd`, so `select sum(cost_usd) from calls` is what indexing the library cost. A
# question is one agent turn. The bucket and the database are billed for what they store; an idle
# queue costs nothing.
#
# ## Clean up
#
# Delete the agent first, since a database an agent has in its tools can't be deleted:
#
# ```python
# noclick.Agent.from_name("call-analyst").delete()
# noclick.Queue.from_name("sales-call-indexing").delete()
# noclick.Database.from_name("sales-calls").delete()
# noclick.Bucket.from_name("sales-calls").delete(force=True)
# ```

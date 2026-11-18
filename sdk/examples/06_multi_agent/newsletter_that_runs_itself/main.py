# ---
# description: A weekly newsletter written by three agents in one room, approved by a person, published on its own site and domain, and emailed to the readers who signed up there.
# card_title: A newsletter that runs itself
# card_line: Written by agents, approved by you.
# mark: newspaper
# cmd: ["python", "06_multi_agent/newsletter_that_runs_itself/main.py"]
# env: ["NOCLICK_API_KEY", "EDITOR_EMAIL", "NEWSLETTER_DOMAIN"]
# deps: []
# ---

# # A newsletter that runs itself
#
# Every Monday at six, a researcher agent finds the week's climate tech news, a writer agent turns
# it into an issue, and an editor agent checks every number against its source and sends the draft
# back until it's right. They work in one [channel](/docs/guide/channels), where each hands off to
# the next by mentioning it. When the editor publishes, the issue waits for a person: the human
# editor gets an email, reads it and approves. Then it's live on the newsletter's own site, and
# within ten minutes it's in the inbox of every reader who signed up there.
#
# Nothing in it runs on your machine once it's set up. This script builds it and, run again, sets
# what it passes on each piece: the site (in `site/` next to this file), its database of readers and
# issues, its domain and email, the three agents and their room. Run it again to see how the latest
# issue went.
#
# It's written the way a newsletter platform would run it for many publications. Each publication
# is one of your [users](/docs/guide/users), and its human editor is the person behind it:
# `EDITOR_EMAIL` gets the approval emails. `NEWSLETTER_DOMAIN` is a domain you own, like
# `fieldnotes.example.com`, that the site serves and the issues are sent from.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# export EDITOR_EMAIL=you@example.com
# export NEWSLETTER_DOMAIN=fieldnotes.example.com
# python 06_multi_agent/newsletter_that_runs_itself/main.py        # set up, and show the latest issue
# python 06_multi_agent/newsletter_that_runs_itself/main.py now    # write this week's issue now
# ```

import os
import sys
from pathlib import Path

import noclick

PUBLICATION_ID = "field-notes"  # your id for this publication
NAME = "Field Notes"
EDITOR_EMAIL = os.environ["EDITOR_EMAIL"]
DOMAIN = os.environ["NEWSLETTER_DOMAIN"]
TIMEZONE = "America/New_York"
SITE = Path(__file__).parent / "site"

# ## The readers and the issues
#
# The publication's [database](/docs/guide/databases) holds what changes from week to week: who
# signed up, and what was published. The site reads issues straight from it, so an issue is live
# the moment its row is written, with no rebuild. A reader is a row the moment they sign up, and a
# subscriber once they click the link in the confirmation email, so nobody can sign up an address
# that isn't theirs. Unsubscribing isn't kept here: every issue goes out as a broadcast, which
# carries its own one-click unsubscribe and skips anyone who used it. A reader who unsubscribed and
# signs up again confirms again too, and confirming lifts their unsubscribe
# (`app.email.resubscribe`), so the table and the broadcast agree.

SCHEMA = {
    "0001_newsletter.sql": """
create table subscribers (
    email text primary key,
    token text not null unique,
    created_at text not null default (datetime('now')),
    confirmed_at text
);
create table issues (
    slug text primary key,
    subject text not null,
    body text not null,
    published_at text not null default (datetime('now')),
    emailed_at text
);
""",
}


def open_database() -> noclick.Database:
    db = noclick.Database.from_name("newsletter", create_if_missing=True)
    db.migrate(SCHEMA)
    return db


# ## The site
#
# The site is a small Next.js app in `site/`: the archive with a signup form, a page per issue,
# the confirm link, and one job that emails new issues. It's a [project](/docs/guide/apps)
# deployed from a [repo](/docs/guide/repos). `commit` with a folder sends only the files that
# changed since the last run and returns `None` when nothing did, so the site deploys only then.
#
# `bind` gives the running site the database as `DB`. The site's code reaches it through
# `Project.current()`, which the deployment signs in as the app, so there's no key in the site.
# The domain serves the site and sends its mail: inbox providers filter newsletters from a shared
# address as spam, and trust mail from the publication's own domain once its records are in place.
# The first run prints the DNS records to add where the domain is hosted. `postal_address` is the
# address every issue's footer carries, as the law asks of bulk mail.
#
# The schedule calls the site's `/jobs/send` every ten minutes, signed so the site can tell the
# call is NoClick's. That job emails any published issue that hasn't gone out, so an issue approved
# at 9:04 is in inboxes by 9:10.

POSTAL_ADDRESS = "Field Notes, 548 Market St #1123, San Francisco, CA 94104"


def deploy_site(db: noclick.Database) -> noclick.Project:
    repo = noclick.Repo.from_name("newsletter-site", create_if_missing=True)
    commit = repo.commit(SITE, message="Update the site", exclude=["node_modules", ".next"])

    app = noclick.Project.from_name("newsletter", repo=repo, framework="nextjs", create_if_missing=True)
    app.bind("DB", db)
    domain = app.add_domain(DOMAIN)
    app.email.enable(domain=DOMAIN, from_address=f"editor@{DOMAIN}", from_name=NAME, postal_address=POSTAL_ADDRESS)
    app.schedule(noclick.Cron("*/10 * * * *"), path="/jobs/send")
    if commit is not None or app.production is None:
        app.deploy().wait()

    for record in domain.refresh().records:
        if record.status != "verified":
            print(f"Add at your DNS host: {record.type} {record.name} {record.value}")
    return app


# ## The newsroom
#
# Three [agents](/docs/guide/agents), each with one job and only the tools it needs:
#
# - The researcher searches the web with Exa (on NoClick's key, nothing to connect), reads the
#   sources, and checks past issues in the database so it doesn't bring last week's news again.
# - The writer has no tools. It writes from the brief, which keeps every claim traceable to a source
#   the researcher found.
# - The editor opens each source to check the draft, and publishes by writing the issue's row.

RESEARCHER = f"""You're the researcher for {NAME}, a weekly newsletter on climate tech for founders and investors.
When you're asked for this week's stories:
1. Find the week's most important climate tech news with exa.search: funding rounds over $10M, policy that
   changes what companies can sell, notable launches and large deployments. Read each source with fetch;
   prefer the company's own announcement plus one independent report.
2. Check the last four issues with query (select subject, body from issues order by slug desc limit 4) and
   drop anything they already covered.
3. Post a brief of the eight strongest stories: two or three sentences of facts each (who, what, how much,
   when) with the source links. End it with @writer.
Facts only. Leave out anything you couldn't source."""

WRITER = f"""You're the writer for {NAME}. When @researcher posts a brief, write this week's issue in Markdown:
- the subject line first, on a line of its own, under 60 characters
- two sentences on the week's biggest story
- five or six stories, each a bold headline and 60 to 90 words on what happened and why it matters to someone
  building or funding a climate company, with the source linked
- a one-line sign-off
Plain words, numbers with units, no hype and no exclamation marks. Post the whole issue and end it with
@editor. When @editor asks for changes, make them and post the whole issue again."""

EDITOR = f"""You're the editor of {NAME}. When @writer posts a draft:
1. Open every source with fetch and check each number and claim against it. Check the issue doesn't repeat
   the last one (query the issues table).
2. If anything is wrong, unsourced, over 900 words or off the house style, tell @writer exactly what to fix.
   Send it back at most twice; after that, fix it yourself.
3. When it's right, publish it with one execute:
   insert into issues (slug, subject, body) values (?, ?, ?)
   with this Monday's date as the slug (YYYY-MM-DD). The human editor approves it before it runs.
4. Post "Waiting for approval: <subject>". When you hear it ran, post "Published: https://{DOMAIN}/<slug>".
   If it's declined, post the note that came with it and send the issue back to @writer."""


# ## One room, every Monday
#
# The three share one room. An agent's message wakes only the agents it mentions, so the researcher's
# brief ends with `@writer`, the draft with `@editor`, and the editor can send it back to `@writer`
# as many times as it needs. You never write the hand-offs: the room is the workflow. Its hard stops
# halt a room that goes in circles, whatever the instructions say: `max_agent_turns` agent turns
# since the last post that wasn't an agent's, and `budget_usd` spent.
#
# The room stays open from week to week, its fields set from this code by `from_name`, and its
# schedule starts each issue: at six on Monday morning it posts the message that mentions
# `@researcher`. Like a person's post it wakes all three; the writer and editor, with nothing yet,
# pass until the brief reaches them.
#
# Each agent's `timezone` starts its every turn with the date and time in New York, so "this week"
# and "this Monday's date" mean what the publication means by them.


def staff(name: str, instructions: str, tools: list) -> noclick.Agent:
    return noclick.Agent.from_name(
        name,
        create_if_missing=True,
        instructions=instructions,
        tools=tools,
        timezone=TIMEZONE,
    )


def open_newsroom(db: noclick.Database) -> noclick.Channel:
    researcher = staff("researcher", RESEARCHER, ["exa.search", "fetch", db.only("query")])
    writer = staff("writer", WRITER, [])
    editor = staff("editor", EDITOR, ["fetch", db.only("query", "execute")])
    return noclick.Channel.from_name(
        "newsroom",
        create_if_missing=True,
        members=[researcher, writer, editor],
        max_agent_turns=16,
        budget_usd=5,
        triggers=[noclick.Cron("0 6 * * 1", tz=TIMEZONE, message="@researcher Good morning. Find this week's stories.")],
    )


# ## A person approves every issue
#
# The editor agent publishes by writing a row, and the publication's
# [policy](/docs/guide/policy) holds every database write an agent makes until a person approves
# that exact call. The approver is the publication's own person, the human editor: they get an
# email with the statement and the issue in it, and approve or decline with a note. Nothing reaches
# the site or a reader before that. The site's own signups aren't agent tool calls, so they're
# never held.
#
# The answer comes back to the room. An approved write runs exactly as it was held, and the editor
# gets a turn with its result, so it posts the link; a declined one gives it a turn with the human
# editor's note, which it passes back to `@writer`.
#
# `code` is denied too. The researcher reads whatever pages the web hands it, and one written to
# talk an agent into running commands finds no shell to run them in. This code owns the
# publication's whole policy, so `Policy.set` replaces it on every run.


def set_rules(publication: noclick.User) -> None:
    noclick.Policy.set(user=publication, deny=["code"], require_approval=["database.execute"])


# ## Write this week's issue now
#
# The schedule posts on Mondays. `now` posts the same message into the room and follows it, so you
# can watch the three agents hand the issue back and forth. It stops when the issue is waiting for
# approval, or when the room halts at one of its stops.


def write_now(room: noclick.Channel) -> None:
    kickoff = room.post("@researcher Find this week's stories.")
    for message in room.stream(after=kickoff):
        print(f"\n--- {message.author.name}\n{message.text}")
        if message.author.type == "system" or message.text.startswith("Waiting for approval"):
            break


# ## How it's going
#
# Every number comes from where it already lives: readers and issues from the database, the
# approval from its request, the next run from the room's schedule, and what it costs from usage.


def status(db: noclick.Database, app: noclick.Project, room: noclick.Channel) -> None:
    readers = db.query("select count(*) as n from subscribers where confirmed_at is not null").rows[0]["n"]
    print(f"\n{NAME} at {app.url}: {readers:,} confirmed signups")
    for issue in db.query("select slug, subject, emailed_at from issues order by slug desc limit 3"):
        print(f"  {issue['slug']}  {issue['subject']}  emailed {issue['emailed_at'] or 'not yet'}")
    for request in noclick.HumanRequest.list(status="pending", kind="approve"):
        print("Waiting for the human editor:", request.url)
    for trigger in room.triggers():
        print("Next issue starts:", trigger.next_run)
    used = app.usage()
    print(f"This month: ${noclick.usage().total_usd:.2f} in all, of which the site ${used.usd:.2f} for {used.requests:,} requests")


# ## Stop it
#
# `stop` closes the room, so its schedule stops and the agents take no more turns. The site keeps
# serving the archive, and the database keeps the readers, until you delete them:
# `app.delete(delete_data=True)` moves the site, its repo and its database to the trash.


def main() -> None:
    publication = noclick.User.from_id(PUBLICATION_ID, create_if_missing=True, name=NAME, email=EDITOR_EMAIL)
    with noclick.as_user(publication):
        if sys.argv[1:] == ["stop"]:
            noclick.Channel.from_name("newsroom").close()
            return
        db = open_database()
        app = deploy_site(db)
        set_rules(publication)
        room = open_newsroom(db)
        if sys.argv[1:] == ["now"]:
            write_now(room)
        status(db, app, room)


if __name__ == "__main__":
    main()

# ---
# description: One support agent on your site's chat, your support email address and a phone number, answering from your help center, looking up the customer's own orders in Stripe, and asking your team before large refunds.
# card_title: One support agent for every channel
# card_line: Chat, email and phone, one agent.
# mark: headset
# cmd: ["python", "02_agents_in_your_product/support_agent/main.py"]
# env: ["NOCLICK_API_KEY", "APP_SECRET", "STRIPE_API_KEY", "SHOP_DOMAIN", "SUPPORT_TEAM_EMAIL", "SUPPORT_TEAM_PHONE"]
# deps: ["fastapi", "uvicorn"]
# featured: true
# ---

# # One support agent for chat, email and phone
#
# Customers reach support three ways: the chat on your site, an email to your support address, and
# a phone call. This example answers all three with one agent. It answers from your help center,
# hands the conversation to a person when the customer asks for one, and, for a customer it knows
# (signed in to the chat, or writing from the email address on their account), looks up their own
# orders in Stripe, refunds small amounts itself and asks your team before larger ones.
#
# One agent means one set of instructions, one knowledge base and one place to read every
# conversation, however it came in. What differs between channels is only who the agent knows it's
# talking to, and that decides what it can see: a known customer's own orders, or nothing but the
# help center.
#
# The folder holds this file (the setup and the backend), `SupportWidget.tsx` (the chat on your
# site) and `help/`, a small help center in Markdown standing in for yours. The example is for a
# coffee roaster, Northwind, that sells through Stripe Checkout.
#
# ```bash
# pip install noclick fastapi uvicorn
# export NOCLICK_API_KEY=nk_live_...                # Full access, from the console's API keys
# export APP_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
# export STRIPE_API_KEY=rk_test_...                 # a restricted key: see below
# export SHOP_DOMAIN=yourshop.com                   # support@help.yourshop.com lives under it
# export SUPPORT_TEAM_EMAIL=support-team@yourshop.com
# export SUPPORT_TEAM_PHONE=+14155550142            # where handed-off calls ring
# python 02_agents_in_your_product/support_agent/main.py
# ```
#
# Running it buys a US phone number, billed monthly. `python main.py clean-up` releases it and
# removes what else the example made.

import base64
import hashlib
import hmac
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response

import noclick

app = FastAPI()

SHOP_DOMAIN = os.environ["SHOP_DOMAIN"]
SUPPORT_DOMAIN = f"help.{SHOP_DOMAIN}"   # the inbox's own subdomain: the shop's mail stays where it is
SUPPORT_TEAM = noclick.Human(
    email=os.environ["SUPPORT_TEAM_EMAIL"],   # refund approvals and handed-off chats and emails
    phone=os.environ["SUPPORT_TEAM_PHONE"],   # handed-off calls
)

# ## A help center the agent can search
#
# A real help center runs to hundreds of articles, far too many to put in every prompt, and the
# customer never uses the article's words: they write "my beans tasted flat", and the answer is
# under "Freshness". So the help center goes in a [database](/docs/guide/databases) the agent
# searches, by meaning and by keyword at once. (If yours fits on a few pages, put it in the
# instructions and skip this section.)
#
# It's a Postgres database, which has pgvector for search by meaning. Each section of each article
# is a row: its text, a link to it, and its embedding from [`AI.embed`](/docs/guide/ai#embeddings).
# `search` is a generated keyword index over the same text, for the words meaning alone misses,
# like "PO box".
#
# The search itself lives in the database too, as a SQL function that ranks by meaning and by
# keyword and fuses the two rankings, so the agent's whole search is one read with the database's
# standard `query` tool. To rank by meaning it needs the question's embedding, and the model has no
# way to make one mid-conversation, so the statement asks for it:
# [`noclick.embed()`](/docs/guide/databases#embed-inside-sql) turns text into a vector, with the
# same model the sections were embedded with, and is billed like `AI.embed`. NoClick embeds the
# text before the statement runs, so the call goes in the statement, as the function's argument,
# never inside the function's body: `select * from search_help(:question, noclick.embed(:question,
# ...))`. It's allowed in a read-only `query`, which is all the agent can run.
#
# `migrate` applies each migration once, in name order, so it runs on every start.

HELP_DIR = Path(__file__).parent / "help"
EMBED_MODEL = "openrouter/openai/text-embedding-3-small"

MIGRATIONS = {
    "0001_help_chunks.sql": """
        create table help_chunks (
            id text primary key,
            title text not null,
            url text not null,
            body text not null,
            content_hash text not null,
            embedding halfvec(1536) not null,
            search tsvector generated always as (to_tsvector('english', title || ' ' || body)) stored
        );
        create index help_chunks_embedding on help_chunks using hnsw (embedding halfvec_cosine_ops);
        create index help_chunks_search on help_chunks using gin (search);
    """,
    "0002_search_help.sql": """
        create function search_help(question text, question_embedding halfvec, k int default 5)
        returns table (id text, title text, url text, body text, score float8)
        language sql stable as $$
            with q as materialized (
                -- any of the question's words, not all of them: questions are long
                select to_tsquery('simple', array_to_string(
                           tsvector_to_array(to_tsvector('english', question)), ' | ')) as ts
            ),
            semantic as (
                select id, row_number() over (order by embedding <=> question_embedding) as rank
                from help_chunks
                order by embedding <=> question_embedding
                limit 20
            ),
            keyword as (
                select id, row_number() over (order by ts_rank_cd(search, (select ts from q)) desc) as rank
                from help_chunks
                where search @@ (select ts from q)
                order by ts_rank_cd(search, (select ts from q)) desc
                limit 20
            )
            select c.id, c.title, c.url, c.body,
                   (coalesce(1.0 / (60 + s.rank), 0) + coalesce(1.0 / (60 + kw.rank), 0))::float8 as score
            from semantic s
            full join keyword kw using (id)
            join help_chunks c using (id)
            order by score desc
            limit k
        $$;
    """,
}


# ## Index it, on every deploy
#
# Each article is split at its `##` headings, so a search returns the section that answers, with a
# link straight to it. A section's hash covers its text and the embedding model, so a deploy
# embeds only the sections that changed, and a section you deleted leaves the index. A new model
# changes every hash, which re-embeds everything: vectors from two models can't be compared.


@dataclass
class Section:
    id: str
    title: str
    url: str
    body: str

    @property
    def content_hash(self) -> str:
        text = f"{EMBED_MODEL}\n{self.title}\n{self.url}\n{self.body}"
        return hashlib.sha256(text.encode()).hexdigest()


def read_help_center() -> list[Section]:
    sections = []
    for path in sorted(HELP_DIR.glob("*.md")):
        header, _, text = path.read_text().removeprefix("---\n").partition("\n---\n")
        article = dict(line.split(": ", 1) for line in header.splitlines())
        intro, *parts = text.split("\n## ")
        if intro.strip():
            sections.append(Section(path.stem, article["title"], article["url"], intro.strip()))
        for part in parts:
            heading, _, body = part.partition("\n")
            anchor = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            title, url = f"{article['title']}: {heading}", f"{article['url']}#{anchor}"
            sections.append(Section(f"{path.stem}#{anchor}", title, url, body.strip()))
    return sections


UPSERT = """
    insert into help_chunks (id, title, url, body, content_hash, embedding)
    values (?, ?, ?, ?, ?, cast(? as halfvec))
    on conflict (id) do update set title = excluded.title, url = excluded.url, body = excluded.body,
        content_hash = excluded.content_hash, embedding = excluded.embedding
"""


def batches(items: list, size: int = 100) -> list:
    """A database `batch` runs up to 100 statements in one transaction."""
    return [items[start:start + size] for start in range(0, len(items), size)]


def index_help_center(help_center: noclick.Database) -> None:
    sections = read_help_center()
    rows = help_center.query("select id, content_hash from help_chunks").rows
    stored = {row["id"]: row["content_hash"] for row in rows}
    changed = [section for section in sections if stored.get(section.id) != section.content_hash]
    for batch in batches(changed):
        vectors = noclick.AI.embed([f"{s.title}\n\n{s.body}" for s in batch], model=EMBED_MODEL).vectors
        upserts = [(UPSERT, [s.id, s.title, s.url, s.body, s.content_hash, v]) for s, v in zip(batch, vectors)]
        help_center.batch(upserts)
    gone = sorted(set(stored) - {section.id for section in sections})
    for batch in batches(gone):
        help_center.batch([("delete from help_chunks where id = ?", [gone_id]) for gone_id in batch])
    print(f"Help center: {len(sections)} sections, {len(changed)} embedded, {len(gone)} removed.")


# ## Stripe, with only the access support needs
#
# The agent looks orders up and refunds them in your Stripe account, through a
# [connection](/docs/guide/connections) holding a key you already have. Make it a restricted key
# (Stripe dashboard > Developers > API keys) that can read Checkout Sessions and Charges and write
# Refunds, and nothing else: then there's nothing else in Stripe the agent could do, however a
# conversation went. NoClick checks the key with Stripe before it saves it. `from_name` creates the
# connection holding the key on the first run and uses it as it is after; `import_` swaps in a
# rotated key.


def stripe_connection() -> noclick.Connection:
    return noclick.Connection.from_name(
        "stripe",
        integration="stripe",
        credential_type="stripe_api_key",
        data={"api_key": os.environ["STRIPE_API_KEY"]},
        create_if_missing=True,
    )


# ## Big refunds wait for your team
#
# A refund of a few dollars shouldn't wait for anyone, and a large one shouldn't go out on a
# model's say-so. A [policy](/docs/guide/policy) rule holds `stripe.create_refund` for a person's
# approval when the amount is over $50, or missing: Stripe refunds the whole charge when `amount`
# is left out, so a missing amount could be anything.
#
# Who approves matters as much as when. Policy asks the user a call is made for, which suits an
# assistant acting in someone's own accounts. Here the user is the customer, who would approve
# their own refund without a second thought. So the [rule](/docs/reference/python/Policy#Rule)
# names its approver: your support team, who get an email with the refund laid out and a page to
# approve or decline it, with a note if they like. `when` is a CEL expression over the call's
# arguments, so the rule only applies to the refunds it describes.
#
# Once the team answers, the agent carries on without the customer having to ask again. An
# approved refund runs exactly as it was held, and the agent gets a turn with its result; a
# declined one gives it a turn with the team's note. Either way it tells the customer where they
# wrote: in the chat, or by reply on their email thread.
#
# `Policy.add` adds the rule to the account's policy and leaves every other rule as it is. A rule
# for the same tool is replaced, so it's safe to run on every deploy.

REFUND_LIMIT_USD = 50


def hold_large_refunds() -> None:
    noclick.Policy.add(
        noclick.Rule(
            "stripe.create_refund",
            when=f"!has(args.amount) || args.amount > {REFUND_LIMIT_USD * 100}",
            approver=SUPPORT_TEAM,
        ),
        to="require_approval",
    )


# ## The agent
#
# It's one agent for your whole account, created outside `as_user`: every customer talks to it, in
# conversations of their own, and its tools act in your account's connections, which is where your
# Stripe and your help center are. Its `budget_usd_per_month` is the ceiling on the whole support
# desk, since mail and calls from people you don't know cost you too.
#
# The agent serves every customer, but a customer should see only their own orders. So which
# customer isn't something the model decides. `bind` fixes `customer` on the order tools to the
# Stripe id on the NoClick user it's talking to, filled in by NoClick at each call: the model never
# sees the parameter and can't pass another, whatever it's asked. The refund tool is bound too, so
# every refund in Stripe records which of your users asked for it. When the agent doesn't know who
# it's talking to (an email from an address it doesn't know, a call), there's no Stripe id to fill
# in, so those tools aren't offered and the agent answers from the help center. A refund takes a
# charge id, which the agent only ever learns from this customer's own charges.
#
# Your support team is a tool too. [`SUPPORT_TEAM.only("hand_off")`](/docs/guide/humans#give-an-agent-a-person)
# gives the agent one way to reach them: handing them the conversation. The team gets a page and an
# email with the transcript and the agent's summary, the agent stays quiet in that conversation,
# and the team's replies reach the customer where they wrote: in the chat, on their email thread,
# or, on a call, by putting the call through to `SUPPORT_TEAM_PHONE`. When they're done,
# `support.hand_back(conversation)` (or the button on their page) gives it back to the agent.

CUSTOMER = "{{user.metadata.stripe_customer}}"

INSTRUCTIONS = f"""You are Northwind Coffee's support agent. Customers reach you in the chat
on our site, by email and by phone.

Answer from the help center, never from memory. Search it with help-center__query:
    select title, url, body from search_help(:question, noclick.embed(:question, '{EMBED_MODEL}'))
with the customer's question as `question`. If it doesn't cover something, say so and offer a person.

Orders: stripe__list_checkout_sessions lists the customer's orders with their items, and
stripe__list_charges their payments and refunds. Both return only the customer you're talking to.
If they aren't available, you don't know who the customer is: offer to hand them to our team, or
ask them to use the chat on our site while signed in, or to email us from the address on their
account.

Refunds: follow the refund policy in the help center. Always pass `amount`, in cents. A refund over
${REFUND_LIMIT_USD} waits for our team: tell the customer it's with the team and that you'll let
them know here.

When the customer asks for a person, is upset, or you can't help, call hand_off with a short summary.

When a customer emails, answer with your reply tool: that's how the email reaches them. In chat and
email, link the help article you used. On a call, speak in short sentences and don't read out
links. Never say something is done until a tool has done it."""


def support_agent(help_center: noclick.Database, stripe: noclick.Connection) -> noclick.Agent:
    return noclick.Agent.from_name(
        "support",
        create_if_missing=True,
        instructions=INSTRUCTIONS,
        tools=[
            help_center.only("query"),
            stripe.only("list_checkout_sessions").bind(
                customer=CUSTOMER, extra_params={"expand": ["data.line_items"]},
            ),
            stripe.only("list_charges").bind(customer=CUSTOMER),
            stripe.only("create_refund").bind(metadata={"requested_by": "{{user.id}}"}),
            SUPPORT_TEAM.only("hand_off"),
        ],
        budget_usd_per_month=300,
    ).hydrate()


# ## Three ways in
#
# ### The chat on your site
#
# The widget is for signed-in customers. Each one is a NoClick [user](/docs/guide/users) under your
# own id for them, with the Stripe customer id you saved at checkout in `metadata`, which is what
# the order tools are bound to. `from_id` with `create_if_missing=True` creates the user on their
# first chat and sets their details on every chat after. `CUSTOMER_CAP_USD` caps what one customer's
# conversations can cost in a month, so nobody can run up your bill by chatting.
#
# The session the browser gets has one scope, `agents`: it can message the support agent as this
# customer and read this customer's conversations, and nothing else. A visitor who isn't signed in
# can still email or call, and the agent's [share page](/docs/guide/sharing) gives them a chat too.
#
# Your site already knows who is signed in. So that this example runs on its own, it keeps them in
# a cookie signed with `APP_SECRET`. Sign in as a customer from your Stripe test mode once:
# `http://localhost:8000/api/demo/sign-in?email=ana@example.com&name=Ana&stripe_customer=cus_...`.

CUSTOMER_CAP_USD = 2.0
SECRET = os.environ["APP_SECRET"].encode()


@dataclass
class Customer:
    id: str
    email: str
    name: str
    stripe_customer: Optional[str]


def signature(body: str) -> str:
    return hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()


def signed_in(request: Request) -> Customer:
    body, _, signed = request.cookies.get("customer", "").rpartition(".")
    if not body or not hmac.compare_digest(signed, signature(body)):
        raise HTTPException(401, "Sign in first.")
    return Customer(**json.loads(base64.urlsafe_b64decode(body)))


@app.get("/api/demo/sign-in")
def demo_sign_in(email: str, name: str, stripe_customer: Optional[str] = None) -> Response:
    customer = {"id": email, "email": email, "name": name, "stripe_customer": stripe_customer}
    body = base64.urlsafe_b64encode(json.dumps(customer).encode()).decode()
    response = Response(f"Signed in as {name}. Open your site.")
    response.set_cookie("customer", f"{body}.{signature(body)}", httponly=True, samesite="lax")
    return response


def customer_user(customer: Customer) -> noclick.User:
    return noclick.User.from_id(
        customer.id,
        create_if_missing=True,
        name=customer.name,
        email=customer.email,
        metadata={"stripe_customer": customer.stripe_customer} if customer.stripe_customer else {},
        spend_cap_usd_per_month=CUSTOMER_CAP_USD,
    )


@app.get("/api/support/session")
def support_session(request: Request, customer: Customer = Depends(signed_in)) -> dict:
    channels = request.app.state.channels
    session = customer_user(customer).session(["agents"], ttl_s=3600)
    return {
        "session": session.token,
        "expires_at": session.expires_at.isoformat(),
        "user_id": customer.id,
        "agent_id": channels.agent.id,
        "email": channels.inbox.address,
        "phone": channels.number.number,
    }


# ### Email to support@
#
# The support address is an [inbox](/docs/guide/inboxes) on your shop's [domain](/docs/guide/domains),
# answered by the same agent. Connect the domain, and the inbox goes on a subdomain of it,
# `help.yourshop.com`: an inbox on a connected domain always does, so your company's mail stays where
# it is. (To keep `support@yourshop.com`, forward it from your mail provider to this address.)
# `Domain.connect` returns the records to add, among them the `NS` records that hand the subdomain to
# NoClick; connecting again returns the same domain. `Inbox.from_name` finds the inbox by the name
# your code gives it, and creates it the first time.
#
# Each email thread is a conversation of its own, so two customers' mail never mixes, and the
# agent answers with a `reply` tool bound to the thread: it goes to the customer who wrote, on their
# thread, and nobody else, including from the turn that resumes once your team answers a refund.
# `senders="anyone"` takes mail from everyone, since plenty of people who write to support have
# never signed in to your site.
#
# A customer who writes from the email address on their user (everyone who has used the chat has
# one) is recognised, whatever `senders` says: their mail provider signs each message (DKIM), so
# NoClick can tell it really came from that address, and a forged `From` line gets nowhere. Their
# turn runs as them, so the order tools fill in their Stripe id, and by email they get their orders
# and refunds as in the chat. Anyone else's mail runs as your account: the order tools have no
# Stripe id to fill in and aren't offered, so the agent answers from the help center and hands
# anything about an order to your team.


@dataclass
class Channels:
    agent: noclick.Agent
    inbox: noclick.Inbox
    number: noclick.PhoneNumber


def support_inbox(support: noclick.Agent) -> noclick.Inbox:
    domain = noclick.Domain.connect(SHOP_DOMAIN)
    inbox = noclick.Inbox.from_name(
        "support", create_if_missing=True, local_part="support", domain=SUPPORT_DOMAIN, agent=support,
        senders="anyone",
    )
    if domain.refresh().status == "pending_dns":
        print(f"Mail to {inbox.address} needs these records in {SHOP_DOMAIN}'s DNS:")
        for record in domain.records:
            print(f"  {record.type} {record.name} {record.value}")
        if domain.setup_url:
            print(f"Or add them in one step: {domain.setup_url}")
    return inbox


# ### A phone number
#
# A [phone number](/docs/guide/phone-numbers) rings the same agent. It talks with the caller, reads
# the help center with the same tool, and when they ask for a person its `hand_off` puts the call
# through to your team's phone. `from_name` buys a local number the first time and finds the same
# one on every run after; `max_monthly_usd` and `max_upfront_usd` are your ceilings on what it costs
# a month and once.
#
# The line answers anyone who calls. A caller ID alone proves nothing, so a call runs as a customer
# only when it comes from a phone they verified with you (`user.verify_phone`) and their carrier
# attests the call came from it; this example doesn't verify customers' phones, so every call runs
# as your account, and a caller gets the help center and a person, never an order lookup.

AREA_CODE = "415"


def support_number(support: noclick.Agent) -> noclick.PhoneNumber:
    number = noclick.PhoneNumber.from_name("support", create_if_missing=True, area_code=AREA_CODE, max_monthly_usd=5,
                                           max_upfront_usd=5)
    return number.answer_with(support)


# ## Run it
#
# `set_up` makes or updates everything, in order, and is safe to run on every deploy. Then the
# server starts. Render `SupportWidget` from `SupportWidget.tsx` on your site, in any React 18 app
# that sends `/api` to this server and has the TypeScript client installed (`npm install noclick`).
#
# Every conversation, on every channel, is in the developer console under the support agent, and
# `support.conversations(user_filter=noclick.ALL_USERS)` reads them from code. Refund approvals and
# handoffs reach `SUPPORT_TEAM_EMAIL`.
#
# The phone number is billed each month, and the database for what it stores. `python main.py
# clean-up` releases the number and deletes the inbox, the agent, the help center and the refund
# rule. It leaves the Stripe connection and the domain, which cost nothing and may be yours for
# other things, and your customers' users.


def set_up() -> Channels:
    help_center = noclick.Database.from_name("help-center", create_if_missing=True, engine="postgres")
    help_center.migrate(MIGRATIONS)
    index_help_center(help_center)
    hold_large_refunds()
    support = support_agent(help_center, stripe_connection())
    return Channels(agent=support, inbox=support_inbox(support), number=support_number(support))


def clean_up() -> None:
    noclick.PhoneNumber.from_name("support").release()
    noclick.Inbox.from_name("support").delete()
    noclick.Agent.from_name("support").delete()
    noclick.Database.from_name("help-center").delete()
    noclick.Policy.remove("stripe.create_refund")


def main() -> None:
    if sys.argv[1:] == ["clean-up"]:
        clean_up()
        return
    app.state.channels = set_up()
    channels = app.state.channels
    print(f"Support answers on {channels.inbox.address}, {channels.number.number} and the chat widget.")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

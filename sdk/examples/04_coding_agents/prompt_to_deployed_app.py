# ---
# description: Your users describe an app, a Codex agent builds it, and it goes live on your domain with the database, email and payments it asks for.
# card_title: Describe an app, get a URL
# card_line: A Codex agent builds it on your domain.
# mark: globe
# cmd: ["python", "04_coding_agents/prompt_to_deployed_app.py"]
# env: ["NOCLICK_API_KEY", "OPENAI_API_KEY", "APPS_DOMAIN"]
# deps: []
# featured: true
# ---

# # Describe an app, get a live URL
#
# One of your users types: "A booking page for my yoga classes. People pick a class, pay $15, and
# get a confirmation email." A few minutes later it's live at `yoga-3f9a1c.yourapps.dev`, saving
# bookings in a database of its own, taking test payments into an account the user will own, and
# sending confirmations from its own address. Then they keep talking: "make the header blue", "add
# a waitlist when a class is full". Each change goes live the same way.
#
# Three pieces do the work:
#
# - A **Codex agent** writes the code, in a [repo](/docs/guide/repos) NoClick hosts.
# - A **project** builds and serves it on a subdomain of your [domain](/docs/guide/domains).
# - **Your code** wires in the services the app says it needs (a database, email, payments, API
#   keys) and deploys, so the model never holds a credential and nothing goes live that didn't build.
#
# Everything belongs to the user who asked for it: their apps, code, data and payments accounts, and
# the agents that build them. Limits keep one user from running up your bill.
#
# You need a ChatGPT API key for Codex to think with, and a name for the domain the apps live on,
# which the first run buys through NoClick.
#
# ```bash
# export OPENAI_API_KEY=sk-... APPS_DOMAIN=yourapps.dev
# python 04_coding_agents/prompt_to_deployed_app.py
# ```

import hashlib
import json
import os
import re
from datetime import datetime, timezone

import noclick

APPS_DOMAIN = os.environ["APPS_DOMAIN"]
SPEND_CAP_USD = 25     # per user a month: sandboxes, builds, and what their apps spend
APP_BUDGET_USD = 10    # per app a month: its hosting, data, email and AI
CHANGES_PER_DAY = 40   # per user: each change is a Codex turn on your ChatGPT key
FIX_ATTEMPTS = 2       # times a failed build goes back to the agent before we give up
PAYMENTS_COUNTRY = "US"  # where your users' businesses are: a payments account stays in its country

# ## A domain for your users' apps
#
# The apps live on a domain your account owns, bought through NoClick. NoClick then hosts its DNS,
# so each new app's web and email records exist the moment the app asks for them, with nothing for
# you to add per app. Make it a domain of its own rather than a subdomain of your product's: apps
# your users build then can't read your product's cookies.
#
# `from_name` with `create_if_missing=True` buys it on the first run and finds it on every run
# after. The purchase is charged to your account in dollars, like everything else, and
# `max_price_usd` is your ceiling. The registry needs a real person as the registrant, who has
# accepted the [registration agreement](/docs/guide/domains#the-registration-agreement)
# (`noclick.Domain.agreement()`): before the first run, set your account's once, in the console or in
# code, with when they accepted it, and every domain your account buys uses it. Privacy protection
# keeps their details off the public record. Until it's set, the purchase raises
# `noclick.ActionRequired`, whose `next_step` links to where it's set, and nothing is bought.
#
# ```python
# noclick.Domain.set_default_registrant(noclick.DomainContact(
#     name="Dana Reyes", email="dana@yourco.test", phone="+14155550188", address="1 Ferry Building",
#     city="San Francisco", region="CA", postal_code="94111", country="US",
#     agreement_accepted_at=accepted_at,   # when Dana accepted the agreement
# ))
# ```
#
# A domain you already own elsewhere works too, connected with `wildcard=True`: its `*` records
# then let every app's subdomain serve and send mail without a record of its own.

MAX_DOMAIN_PRICE_USD = 20


def apps_domain() -> noclick.Domain:
    try:
        domain = noclick.Domain.from_name(
            APPS_DOMAIN, create_if_missing=True, max_price_usd=MAX_DOMAIN_PRICE_USD,
        ).hydrate()
    except noclick.ActionRequired as err:
        raise SystemExit(f"{err.message}\n{err.next_step}") from None
    if domain.source != "bought" and not domain.wildcard:
        raise SystemExit(f"Connect {APPS_DOMAIN} with noclick.Domain.connect(..., wildcard=True) first.")
    return domain


# ## One ChatGPT key for every user's agent
#
# Codex thinks with a ChatGPT key held in a
# [model provider's connection](/docs/guide/connections#model-providers). This one is your
# account's, and every user's builder agent thinks with it, so the key is stored once and rotated
# in one place. Only a key acting for your whole account can hand a user's agent a connection of
# the account's, and neither the user nor their agent can read the key.


def house_openai() -> noclick.Connection:
    return noclick.Connection.from_name(
        "openai", integration="openai", data={"api_key": os.environ["OPENAI_API_KEY"]}, create_if_missing=True,
    )


# ## What the agent is told
#
# The agent gets the stack (Next.js), the loop (build, commit, push), and a menu of services. It
# declares the ones the app needs in `services.json` at the root of the repo, and your code reads
# that file after each turn. A tip calculator declares nothing; the yoga studio declares a
# database, email and payments. Every service is then tied to a real need of the app, and the
# decision to create one stays in your code, where you can check it.
#
# The services reach the running app without a credential in its code. The app's own code calls
# `Project.current()`, which the deployment signs in as the app, and reaches its database binding,
# its email and AI through it; payments use keys NoClick keeps in the app's secrets. The instructions
# name the payment processor those keys are for (`processor`, the same for every app, so it's known
# before any account is open), and the agent writes the payment code in the same change that
# declares payments.
#
# Everything the app does is billed to your account and counts toward its budget. Once that's used
# up, the app keeps serving and reading its data, but its writes and AI calls fail, so the agent is
# told to catch that and keep the page working. Its email waits (`held`) and goes out once the app
# can pay again, so a form saves what it can and always tells the visitor their message arrived.


def builder_instructions(slug: str, host: str, processor: str) -> str:
    return f"""You build and change one web app for the person you're talking to. It's live at
https://{host}.

The code is a Next.js 16 app (App Router, TypeScript; "next": "^16.4.1" in package.json, the
releases the platform builds) in /workspace/{slug}, a checkout of the app's repository. The first
message describes the app; later ones ask for changes. For each:

1. Make the change. Keep the app small and plain: no extra services, no background workers.
2. Run `npm run build` and fix every error.
3. Commit and push to main. Pushing is what ships: after your turn, the platform sets up the
   services the app declares, applies new migrations, and deploys main.

Declare what the app needs in services.json at the repository root, and only what it needs:
{{"database": true, "email": true, "payments": true, "secrets": ["WEATHER_API_KEY"]}}

- database: a SQL database (SQLite). In server code, `import {{ Project }} from "noclick"`, then
  `const db = await Project.current().database("DB")`: `await db.query(sql, params)` reads and
  `await db.execute(sql, params)` writes, with `?` placeholders. Keep the schema in
  migrations/NNNN_name.sql, one new file per change, and never edit one you've pushed. Migrations
  run before the new code goes live, so only add tables and columns.
- email: transactional email from the app's own address, with
  `await Project.current().email.send({{ to, subject, text, html, idempotencyKey }})`. Receipts,
  confirmations and sign-in codes only, never marketing. While the app can't pay, a send resolves
  `held` and goes out once it can; pass `timeSensitive: true` for a sign-in link or a password
  reset, which is no use late, so it throws instead.
- payments: a payments account the app's owner will own, at {processor}: take payments with the
  `{processor}` npm package. Its keys are in PAYMENTS_SECRET_KEY, PAYMENTS_PUBLISHABLE_KEY and
  PAYMENTS_WEBHOOK_SECRET. It runs in test mode until the owner claims it, so never hardcode a key
  or assume live mode.
- secrets: the names of other API keys the app reads from process.env. Never put a key in code;
  the person adds each one themselves.

AI needs no declaration: in server code, `const reply = await Project.current().ai.chat(prompt)`
calls a model, and `reply.text` is its answer.

Use the database, email, AI and payment keys from server code only, never in the browser.

The app has a monthly budget. Once it's used up, the app keeps serving pages and reading its data,
but database writes and AI calls throw `SpendCapExceeded` (or `PaymentRequired`), both exported by
"noclick". Catch them where you make those calls and keep the page working: show it without the AI
part, or tell the visitor to try again later. Never let one become an error page.

A form a visitor sends (a contact form, a booking request) saves the submission to the database
first, then sends its email, and tells the visitor it was received whatever the email answers.

Reply in two or three plain sentences for the person: what changed, and anything they need to do.
Don't paste code."""


# ## Open an app
#
# An app is three things with the same name, all created inside `as_user`, so they belong to that
# user: a repo for the code, a [project](/docs/guide/apps) that builds and serves it, and a Codex
# agent whose workspace holds a checkout of that repo. `repo.checkout(push=["main"])` clones it at
# the conversation's first turn and signs the agent's git in for that one repo, able to push to
# `main` and nothing else. The agent can't reach anything else: not the user's other apps, not
# your account. `builder_for` runs before every turn, so the agent matches this code. Codex reads
# its instructions when a conversation starts, though, so an app that's already being built keeps
# the instructions it started with.
#
# The user is created on first use with a monthly spend cap. It covers everything NoClick bills
# for their apps: the agent's sandbox time, builds, hosting, email and the apps' AI. Each app and
# each builder agent also has its own `budget_usd_per_month`, so one busy app can't spend the whole
# cap.
#
# The app's address is a subdomain of your domain, which a user's project may take from a key
# acting for your whole account; under a domain bought through NoClick its record is written at
# once. The subdomain carries a hash of the user's id, so two users can both call their app `todo`.


def user_for(user_id: str) -> noclick.User:
    return noclick.User.from_id(user_id, create_if_missing=True, spend_cap_usd_per_month=SPEND_CAP_USD)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "app"


def host_for(user_id: str, slug: str) -> str:
    return f"{slug}-{hashlib.sha256(user_id.encode()).hexdigest()[:6]}.{APPS_DOMAIN}"


def open_app(user_id: str, name: str) -> str:
    slug = slugify(name)
    host = host_for(user_id, slug)
    with noclick.as_user(user_for(user_id)):
        repo = noclick.Repo.from_name(slug, create_if_missing=True)
        app = noclick.Project.from_name(
            slug, repo=repo, framework="nextjs", budget_usd_per_month=APP_BUDGET_USD, create_if_missing=True,
        )
        if host not in app.domain_names:
            app.add_domain(host)
    return slug


def builder_for(slug: str, host: str, openai: noclick.Connection) -> noclick.Agent:
    repo = noclick.Repo.from_name(slug)
    processor = noclick.Project.from_name(slug).payments.status().processor
    return noclick.Agent.from_name(
        f"builder-{slug}",
        create_if_missing=True,
        harness="codex",
        model_connection=openai,
        instructions=builder_instructions(slug, host, processor),
        repos=[repo.checkout(push=["main"])],
        budget_usd_per_month=10,
    )


# ## Wire in what the app asked for
#
# After a turn that pushed, your code reads `services.json` from the repo and makes each service
# real. Every call here is safe to repeat, so it runs after every change.
#
# - **database**: a [database](/docs/guide/databases) of the app's own, bound as `DB`. Then the
#   repo's `migrations/` folder goes to `migrate`, which applies only the files it hasn't run yet,
#   in one transaction. Without it the app has nowhere to keep a booking.
# - **email**: sending from `noreply@` the app's subdomain, on your domain, so confirmations come
#   from the app rather than from a shared address.
# - **payments**: a payments account in test mode, in `PAYMENTS_COUNTRY`, with its keys in the
#   app's secrets. It belongs to whoever claims it, so the user who built the app claims it and gets
#   paid directly. The payment code is already written against the processor the agent was told, so
#   it works on the first deploy.
# - **secrets**: the names the app reads from its environment. The user sets each value with
#   `/secret NAME value` in the chat, straight into the app's secrets: the value never passes
#   through the model or the code.


def read_services(repo: noclick.Repo) -> dict:
    try:
        return json.loads(repo.read("services.json"))
    except noclick.NotFound:
        return {}


def apply_migrations(repo: noclick.Repo, data: noclick.Database) -> None:
    try:
        entries = repo.files("migrations/")
    except noclick.NotFound:
        return
    migrations = {
        entry.path.rsplit("/", 1)[-1]: repo.read(entry.path).decode()
        for entry in entries
        if entry.type == "file" and entry.path.endswith(".sql")
    }
    if migrations:
        data.migrate(migrations)


def provision(slug: str, host: str) -> list[str]:
    repo = noclick.Repo.from_name(slug)
    app = noclick.Project.from_name(slug)
    services = read_services(repo)
    notes = []
    if services.get("database"):
        data = noclick.Database.from_name(f"{slug}-data", create_if_missing=True)
        app.bind("DB", data)
        apply_migrations(repo, data)
    if services.get("email"):
        app.email.enable(domain=host)
    if services.get("payments"):
        payments = app.payments.enable(country=PAYMENTS_COUNTRY)
        if payments.mode == "test":
            notes.append(f"Payments take test cards for now. To take real money, claim the account: {payments.claim_url}")
    missing = sorted(set(services.get("secrets", [])) - set(app.secrets.list()))
    if missing:
        notes.append("The app needs " + ", ".join(missing) + ". Add each with /secret NAME value.")
    return notes


# ## Ship it
#
# `deploy` builds the head of `main` and returns an [operation](/docs/guide/operations). If the build
# fails, production keeps serving the last good deployment, and the build log goes back to the
# agent in the same conversation to fix. A migration that doesn't apply goes back the same way.
# After `FIX_ATTEMPTS` tries the change is reported as failed, and the live app is untouched.


class BuildFailed(Exception):
    pass


def ship(slug: str, host: str, builder: noclick.Agent) -> list[str]:
    attempts = 0
    while True:
        try:
            notes = provision(slug, host)
            noclick.Project.from_name(slug).deploy().wait()
            return notes
        except noclick.OperationFailed as failed:
            broken = noclick.Deployment.get(failed.deployment_id)
            problem = "The build failed. The end of its log:\n" + "\n".join(
                line.message for line in broken.logs(kind="build")[-80:]
            )
        except noclick.InvalidRequest as failed:
            problem = f"Setting up the app failed: {failed.message}"
        attempts += 1
        if attempts > FIX_ATTEMPTS:
            raise BuildFailed(problem)
        builder.message(f"{problem}\n\nFix it, then commit and push.", conversation="build")


# ## Change it by chatting
#
# Each message is one Codex turn in the app's one conversation, so "make it blue" knows what "it"
# is. A turn that doesn't push (a question, or a request the agent pushes back on) only answers;
# a turn that pushes ships.
#
# Two limits run before any work. NoClick's spend cap covers what NoClick bills, but Codex's
# tokens are billed to your ChatGPT key, so a [dict](/docs/guide/dicts) counts each user's changes
# per day: `increment` is atomic, and its key expires on its own. The dict is your account's, so
# users can't reset it. When the user's spend cap is reached, NoClick refuses the turn with
# `noclick.SpendCapExceeded` before any work starts.
#
# In a web app, run `change` in a background job: a first build takes a few minutes.


def within_daily_limit(user_id: str) -> bool:
    changes = noclick.Dict.from_name("app-builder-changes", create_if_missing=True)
    today = datetime.now(timezone.utc).date().isoformat()
    return changes.increment(f"{user_id}:{today}", ttl_s=2 * 86400) <= CHANGES_PER_DAY


def head(repo: noclick.Repo) -> str | None:
    last = repo.refresh().last_commit
    return last.sha if last else None


def change(user_id: str, slug: str, text: str, openai: noclick.Connection) -> str:
    if not within_daily_limit(user_id):
        return f"That's {CHANGES_PER_DAY} changes today. Try again tomorrow."
    host = host_for(user_id, slug)
    with noclick.as_user(user_for(user_id)):
        repo = noclick.Repo.from_name(slug)
        builder = builder_for(slug, host, openai)
        try:
            before = head(repo)
            reply = builder.message(text, conversation="build")
            if head(repo) == before:
                return reply.text
            notes = ship(slug, host, builder)
        except noclick.SpendCapExceeded:
            return "You've reached this month's limit for your apps."
        except BuildFailed as failed:
            return f"That change didn't build, so the live app is unchanged.\n{failed}"
        spent = noclick.usage().total_usd
    lines = [reply.text, f"Live at https://{host}", *notes, f"This month: ${spent:.2f} of ${SPEND_CAP_USD}"]
    return "\n".join(lines)


def set_secret(user_id: str, slug: str, command: str) -> str:
    parts = command.split(maxsplit=2)
    if len(parts) != 3:
        return "Use /secret NAME value"
    _, name, value = parts
    with noclick.as_user(user_for(user_id)):
        app = noclick.Project.from_name(slug)
        app.secrets.set(name, value)
        app.deploy().wait()
    return f"{name} is set and the app has been redeployed with it."


# ## Try it
#
# This runs the service for one user, `user_42`, in your terminal. Describe an app in your first
# message, then ask for changes; `/secret NAME value` sets an API key the app asked for, and an
# empty line quits. Run it again with the same name to pick the conversation up where it stopped.


def main() -> None:
    apps_domain()
    openai = house_openai()
    user_id = "user_42"
    slug = open_app(user_id, input("Name your app: "))
    print(f"Describe it, then ask for changes. It will live at https://{host_for(user_id, slug)}")
    while text := input("> ").strip():
        if text.startswith("/secret "):
            print(set_secret(user_id, slug, text))
        else:
            print(change(user_id, slug, text, openai))


if __name__ == "__main__":
    main()

# ## Clean up
#
# An app costs nothing while nobody visits it, apart from its storage. To delete one, delete its
# agent, then the project with `delete_data=True`, which moves its repo and its database to the
# trash with it (each restorable for 30 days):
#
# ```python
# with noclick.as_user("user_42"):
#     noclick.Agent.from_name("builder-yoga-classes").delete()
#     noclick.Project.from_name("yoga-classes").delete(delete_data=True)
# ```
#
# A payments account stays with the person who claimed it. Your domain stays yours, and renews
# each year until you turn off `auto_renew`.

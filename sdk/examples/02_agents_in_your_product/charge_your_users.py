# ---
# description: Prepaid credits for your users on your own Stripe. Their agents' usage comes off their balance as it happens, they're paused with a top-up link when it runs low, and what they sent meanwhile runs once they pay.
# card_title: Charge users for their agents
# card_line: Prepaid credits on your Stripe.
# mark: automation-stripe
# cmd: ["python", "02_agents_in_your_product/charge_your_users.py"]
# env: ["NOCLICK_API_KEY", "STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET", "TOP_UP_LINK_SECRET", "PUBLIC_URL"]
# deps: ["fastapi", "uvicorn", "stripe"]
# ---

# # Charge your users for what their agents use
#
# NoClick bills your account for everything your users' agents do, in dollars. What you charge
# your users is up to you, and so is how: this example sells prepaid credits through your own
# Stripe account, so the money lands in your bank. Your users pay a markup on what NoClick costs
# you, their balance goes down as their agents work, and when it runs low they're told how to top
# up, in your words, wherever they were talking to the agent.
#
# Three NoClick pieces do it, and your server owns everything else:
#
# - **`usage.recorded`** events tell your server about each step of spend for a user (a turn, an AI
#   request, a call) a few seconds after it happens. Your ledger debits them.
# - **`user.pause_spending()`** stops a user's spending, with your message and your top-up link.
#   Nothing that costs money runs for them until you resume them; messages they send meanwhile are
#   answered with your message and held.
# - **`user.resume_spending()`** lets them go on once they've paid, and what was held runs.
#
# The ledger lives in your database (SQLite here), the checkout in your Stripe account. To switch
# to a monthly plan, or to billing at the end of the month, you change this file, not NoClick.
#
# You need a public `https` address for this server (`PUBLIC_URL`; a tunnel works while you try it),
# a Stripe webhook endpoint pointing at `PUBLIC_URL/stripe/webhook` for `checkout.session.completed`
# (its signing secret is `STRIPE_WEBHOOK_SECRET`), and any long random string as
# `TOP_UP_LINK_SECRET`.
#
# ```bash
# pip install noclick fastapi uvicorn stripe
# export NOCLICK_API_KEY=nk_live_... STRIPE_API_KEY=sk_test_... STRIPE_WEBHOOK_SECRET=whsec_...
# export TOP_UP_LINK_SECRET=$(openssl rand -hex 32) PUBLIC_URL=https://your-tunnel.example
# python 02_agents_in_your_product/charge_your_users.py
# ```

import hashlib
import hmac
import math
import os
import sqlite3
import threading
import time

import stripe
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

import noclick

PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")
stripe.api_key = os.environ["STRIPE_API_KEY"]

# ## Your prices
#
# Everything NoClick reports is what it costs you, in dollars. You charge your users `MARKUP`
# times that. Balances are kept in millionths of a dollar of your price, so tiny steps add up
# exactly.
#
# A user is paused at `PAUSE_BELOW`, not at zero. Your server hears of each step a few seconds
# after it settles, and the work in flight when you pause finishes, so a little margin keeps a
# user from running past what they paid for. The spend cap set below is the hard ceiling no delay
# can cross.

MARKUP = 3
MICROS = 1_000_000
WELCOME_CREDITS = 0.10   # dollars, small so the demo pauses quickly
PAUSE_BELOW = 0.02
MIN_TOP_UP = 5.00

# ## The ledger
#
# One balance per user, and the keys of everything already applied, so a webhook that arrives
# twice is counted once. NoClick can deliver an event more than once, and so can Stripe.

db = sqlite3.connect("credits.db", check_same_thread=False, isolation_level=None)
db.executescript("""
CREATE TABLE IF NOT EXISTS balances (user_id TEXT PRIMARY KEY, micros INTEGER NOT NULL, paused INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS applied (key TEXT PRIMARY KEY);
""")
lock = threading.Lock()


def apply(user_id: str, micros: int, key: str) -> None:
    """Add ``micros`` (negative to debit), once per key."""
    with lock:
        db.execute("BEGIN IMMEDIATE")
        try:
            if not db.execute("SELECT 1 FROM applied WHERE key = ?", (key,)).fetchone():
                db.execute("INSERT INTO applied (key) VALUES (?)", (key,))
                db.execute(
                    "INSERT INTO balances (user_id, micros) VALUES (?, ?) "
                    "ON CONFLICT (user_id) DO UPDATE SET micros = micros + excluded.micros",
                    (user_id, micros),
                )
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def account_of(user_id: str):
    """(balance in micros, whether you've paused them)."""
    with lock:
        row = db.execute("SELECT micros, paused FROM balances WHERE user_id = ?", (user_id,)).fetchone()
    return (row[0], bool(row[1])) if row else (0, False)


def set_paused(user_id: str, paused: bool) -> None:
    with lock:
        db.execute("UPDATE balances SET paused = ? WHERE user_id = ?", (int(paused), user_id))


# ## A top-up link that never goes stale
#
# The link a paused user gets is the `action` you pause them with: your page, your checkout. A
# Stripe Checkout Session made ahead of time expires within a day, and the user may open the
# message later than that. So the link points at this server, and the checkout is made when it's
# opened, for whatever the user is short right then (at least `MIN_TOP_UP`).
#
# The link is signed, so nobody can make one for another user, and carries nothing else: the
# amount is worked out from the ledger when it's opened, never taken from the URL.


def sign(user_id: str) -> str:
    return hmac.new(os.environ["TOP_UP_LINK_SECRET"].encode(), user_id.encode(), hashlib.sha256).hexdigest()[:32]


def top_up_link(user_id: str) -> str:
    return f"{PUBLIC_URL}/top-up/{user_id}?sig={sign(user_id)}"


app = FastAPI()


@app.get("/top-up/{user_id}")
def top_up(user_id: str, sig: str):
    if not hmac.compare_digest(sig, sign(user_id)):
        raise HTTPException(404)
    short = PAUSE_BELOW * MICROS - account_of(user_id)[0]
    cents = max(math.ceil(MIN_TOP_UP * 100), math.ceil(short / 10_000))
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {"currency": "usd", "product_data": {"name": "Credits"}, "unit_amount": cents},
            "quantity": 1,
        }],
        client_reference_id=user_id,
        success_url=f"{PUBLIC_URL}/paid",
        cancel_url=f"{PUBLIC_URL}/paid",
    )
    return RedirectResponse(session.url, status_code=303)


@app.get("/paid")
def paid():
    return {"ok": "Thanks. Your agent picks up where you left off."}


# ## Usage comes in, the balance goes down
#
# Each `usage.recorded` event is one step of spend for one of your users: `data.usd` is what it
# cost you, and `data.lines` what it was made of (tokens, seconds of a call). Its `event.id` is the
# key that makes a second delivery harmless.
#
# When a user's balance is under `PAUSE_BELOW`, pause them with what they can do about it. Keep the
# link out of the message: on a phone call NoClick reads the message aloud, and everywhere else the
# action follows it as a button or a link. The check reads the balance rather than this one debit,
# so an event retried after a failed pause still pauses them, and the ledger remembers the pause, so
# NoClick hears about it once.
#
# The two `user.spending.*` events keep the ledger in step when someone pauses or resumes a user
# from the console instead.


def handle_noclick_event(event: noclick.Event) -> None:
    if event.type == "usage.recorded":
        usage = event.data
        user_id = usage["user_id"]
        apply(user_id, -round(usage["usd"] * MARKUP * MICROS), key=event.id)
        balance, paused = account_of(user_id)
        if balance < PAUSE_BELOW * MICROS and not paused:
            noclick.User.from_id(user_id).pause_spending(
                message="You've used your credits. Top up to keep going.",
                action=("Top up", top_up_link(user_id)),
            )
            set_paused(user_id, True)
    elif event.type in ("user.spending.paused", "user.spending.resumed"):
        set_paused(event.data["user_id"], event.type == "user.spending.paused")


@app.post("/noclick/events")
async def noclick_events(request: Request):
    try:
        event = noclick.Webhook.verify(await request.body(), request.headers, app.state.noclick_secret)
    except noclick.WebhookSignatureError:
        raise HTTPException(400)
    handle_noclick_event(event)
    return {}


# ## Payment comes in, the user goes on
#
# Stripe tells your server when a checkout is paid, naming the user by the `client_reference_id`
# the link put on it. Credit them what they paid, keyed by the session so a retried webhook pays
# once, and resume them if they're above the margin again. What they sent while paused runs now,
# each message starting with when it arrived, so the agent knows it waited.


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    try:
        event = stripe.Webhook.construct_event(
            await request.body(), request.headers.get("stripe-signature", ""), os.environ["STRIPE_WEBHOOK_SECRET"],
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400)
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session["client_reference_id"]
        if session["payment_status"] == "paid" and user_id:
            apply(user_id, session["amount_total"] * 10_000, key=f"stripe:{session['id']}")
            balance, paused = account_of(user_id)
            if balance >= PAUSE_BELOW * MICROS and paused:
                noclick.User.from_id(user_id).resume_spending()
                set_paused(user_id, False)
    return {}


# ## A user, a ceiling and some credits to start
#
# Your users are NoClick users under your own ids. `spend_cap_usd_per_month` is the ceiling in
# NoClick's dollars: whatever happens to your server or your webhooks, one user can't cost you more
# than this in a month. New users get a few welcome credits, once.


def onboard(user_id: str, email: str) -> noclick.User:
    user = noclick.User.from_id(user_id, create_if_missing=True, email=email, spend_cap_usd_per_month=5)
    apply(user_id, round(WELCOME_CREDITS * MICROS), key=f"welcome:{user_id}")
    return user


# ## Hear about usage
#
# One webhook endpoint for your account hears every user's events. `from_name` creates it the
# first time and sets its events after that, every time this runs. The secret is on the object only when this
# call created it; afterwards `reveal_secret()` reads it, with a key that has the `webhooks:reveal`
# scope.


def listen_for_usage() -> str:
    hook = noclick.Webhook.from_name(
        f"{PUBLIC_URL}/noclick/events",
        create_if_missing=True,
        events=["usage.recorded", "user.spending.*"],
    )
    return hook.secret or hook.reveal_secret()


# ## Try it
#
# The demo talks to an agent as `user_42` until the credits run out. Each reply's usage arrives on
# your server, the balance drops, and the user is paused: the next message raises
# `noclick.SpendingPaused`, whose `user_message` and `action` are what you'd show them in your
# app; by email or on a call, NoClick tells them itself. Open the link, pay with a Stripe test card,
# and the user is resumed.


def demo() -> None:
    time.sleep(2)  # let the server start
    user = onboard("user_42", "ana@example.com")
    agent = noclick.Agent.from_name(
        "assistant", create_if_missing=True, instructions="You answer briefly and well.",
    )
    for question in ["Plan a three-day trip to Lisbon.", "Now one for Porto.", "And for the Algarve."] * 5:
        try:
            agent.message(question, user=user)
        except noclick.SpendingPaused as paused:
            label, url = paused.action
            print(f"\n{user.id} is paused. They see: {paused.user_message} [{label}] {url}")
            return
        time.sleep(5)  # usage arrives a few seconds after each turn
        print(f"{user.id} has ${account_of(user.id)[0] / MICROS:.4f} left")
    print("Still going: lower WELCOME_CREDITS to see a pause sooner.")


def main() -> None:
    app.state.noclick_secret = listen_for_usage()
    threading.Thread(target=demo, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()

# ## Other ways to charge
#
# The same three pieces fit any model, because the model lives in your code:
#
# - **A monthly plan with an allowance**: credit the allowance on each paid invoice instead of on a
#   checkout, and pause at the margin as here.
# - **Billing at the end of the month**: send each `usage.recorded` to your payment processor's meter
#   (whose usage, `data.usd` or a line's `quantity`, `data.occurred_at`, and `event.id` as the
#   idempotency key) and invoice from it; pause a user whose invoice goes unpaid.
# - **A team's shared pool**: key the ledger by the team, not the user, and pause every member when
#   it runs low.
#
# What a user may do at all, whatever their balance (web search only on your Pro plan, say), is
# your policy: a `deny` rule with a condition on `user.metadata` and a `message` saying how to get
# it. See [Charging your users](/docs/guide/spend#charging-your-users).
#
# ## What it costs
#
# NoClick charges your account for the agent's turns as usual; the webhook, the events and pausing
# are free. Stripe charges its own fees on each top-up.
#
# ## Clean up
#
# ```python
# noclick.Webhook.from_name(f"{PUBLIC_URL}/noclick/events").delete()
# noclick.Agent.from_name("assistant").delete()
# noclick.User.from_id("user_42").delete()
# ```
#
# and delete `credits.db`.

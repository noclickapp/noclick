# ---
# description: Create a user under your own id, let them connect their Gmail, then read their inbox from your code and from their own agent.
# card_title: Connect your first user
# card_line: A user signs in; their agent reads Gmail.
# mark: automation-gmail
# cmd: ["python", "01_getting_started/connect_a_user.py"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # Connect your first user
#
# Your product acts for people: it reads their email, books into their calendar, posts in their
# Slack. In this example you create one of your users in NoClick, under the id your product
# already has for them, and send them a link to connect their Gmail. Once they do, your code
# reads their inbox, and an agent of their own answers questions about it. You never see or
# store their Google token.
#
# You play the user: the script prints a link, you connect your own Gmail, and the rest runs
# against your inbox. Nothing is sent, archived or deleted.
#
# ```bash
# export NOCLICK_API_KEY=nk_live_...
# python 01_getting_started/connect_a_user.py
# ```

import noclick

# ## A user is your id for someone
#
# A [user](/docs/guide/users) is someone your product acts for. NoClick keys them by the id you
# already use, such as a primary key in your own database or an Auth0 subject, and never issues
# another. Their connections, agents, conversations and spend belong to them and nobody else.
#
# `from_id` with `create_if_missing=True` creates the user the first time it's used, so you don't
# need a sign-up hook: the same line works for a new user and a returning one. The user needs no
# email address here, since you'll hand them the link yourself.

YOUR_ID_FOR_ANA = "user_42"


def ana() -> noclick.User:
    return noclick.User.from_id(YOUR_ID_FOR_ANA, create_if_missing=True, name="Ana Lima")


# ## A connection is a name for one of their accounts
#
# A [connection](/docs/guide/connections) is one account on another service under a name you
# choose. Inside `noclick.as_user(user)`, every call acts for that user, so `"gmail"` here is
# Ana's Gmail, not yours, and another user's `"gmail"` is theirs.
#
# A new connection is **pending**: no account is connected yet, and `connect_url` is the page
# where the user signs in to Google. `reason` appears on that page, so say why you're asking.

REASON = "to find the emails that still need your reply"


def ana_gmail() -> noclick.Connection:
    return noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True, reason=REASON)


# ## What a pending connection does
#
# Before Ana connects, anything that needs her account says so rather than failing
# mysteriously. `run` raises `noclick.NeedsConnection`, which carries the same link, so the code
# that hit the gap can hand it on. Once she has connected, a revoked account raises
# `noclick.CredentialDisconnected` the same way, with a link to reconnect. A
# [toolkit](/docs/guide/toolkits) or an agent given the connection does the same in its own way:
# the tool's result holds the link, and the agent passes it on in its reply.


def show_pending(gmail: noclick.Connection) -> None:
    print(f"status: {gmail.status}")
    try:
        gmail.run("fetch_emails_from_inbox", {"max_results": 1})
    except (noclick.NeedsConnection, noclick.CredentialDisconnected) as err:
        print(f"{err.message}\n  link: {err.connect_url}")


# ## Send them the link, and wait
#
# In your product, `connect_url` goes behind a "Connect Gmail" button. Here it's printed. When Ana
# opens it she sees:
#
# 1. A page in your [brand](/docs/guide/brand) (NoClick's, until you set one), naming the service
#    and your reason.
# 2. Google's own sign-in and consent screen, listing what the connection may do.
# 3. A page saying she's done. With `redirect_url=` on the connection, she lands back in your
#    product instead, with `status=success` in the query string.
#
# `wait()` returns once an account is connected, and at once when it already is. A link stays open
# for 7 days; when a rerun finds the last one lapsed, `connect_link()` mints a fresh one, and
# `refresh()` reloads the connection so `wait()` follows it. In a web server, don't block a request
# on `wait()`: check `gmail.refresh().connected` when she comes back.


def connect(gmail: noclick.Connection) -> None:
    if gmail.connect_url is None:
        gmail.connect_link(reason=REASON)
        gmail.refresh()
    print(f"\nOpen this link and connect your Gmail (you're Ana now):\n  {gmail.connect_url}\n")
    gmail.wait()


# ## Act in their account
#
# `run` executes one of the integration's operations in exactly this account and returns its
# result as plain data. `account` names the account the provider says was connected.
# `gmail.operations()` lists what Gmail can do, with each operation's parameters.


def recent_mail(gmail: noclick.Connection) -> None:
    print(f"Connected as {gmail.account}")
    inbox = gmail.run(
        "fetch_emails_from_inbox",
        {"query": "in:inbox newer_than:7d", "max_results": 5, "include_body": False},
    )
    for email in inbox["emails"]:
        print(f"  {email['date'][:16]}  {email['from'][:32]:<32}  {email['subject']}")


# ## Hand the same connection to their agent
#
# An agent created inside `as_user` belongs to that user and acts in that user's connections,
# wherever you message it from. `gmail.only(...)` gives it two read operations and nothing that
# sends, archives or deletes: a model gets the smallest set of tools that does the job.
#
# Run this for another user and they get their own agent, reading their own Gmail, from the same
# code.


def ask_her_agent(gmail: noclick.Connection) -> None:
    assistant = noclick.Agent.from_name(
        "inbox-assistant",
        create_if_missing=True,
        instructions="You help the user with their email. Read before you answer, and quote senders by name.",
        tools=[gmail.only("fetch_emails_from_inbox", "fetch_email_thread")],
    )
    reply = assistant.message("Which emails from this week still need a reply from me?")
    print(f"\n{reply.text}")


def main() -> None:
    user = ana()
    with noclick.as_user(user):
        gmail = ana_gmail()
        if not gmail.connected:
            show_pending(gmail)
            connect(gmail)
        recent_mail(gmail)
        ask_her_agent(gmail)
    print(f"\nEverything done for Ana, in the console: {user.console_url}")


if __name__ == "__main__":
    main()

# ## Run it again
#
# The second run finds Ana, finds her connected Gmail and goes straight to her inbox: every line
# above is safe to repeat. If she revokes NoClick's access in her Google account, the connection
# turns `disconnected` and keeps its name, so the same code sends her through a fresh link, and
# everything that names `gmail` works again once she reconnects. `gmail.request(reason=...)` emails
# her the link instead, when she has an email address.
#
# ## Clean up
#
# Deleting the connection disconnects NoClick from her Google account and leaves the user. Deleting
# the user does that for every connection she has, and frees the id for reuse; her conversations
# and what she spent stay readable:
#
# ```python
# with noclick.as_user("user_42"):
#     noclick.Agent.from_name("inbox-assistant").delete()
# noclick.User.from_id("user_42").delete()
# ```

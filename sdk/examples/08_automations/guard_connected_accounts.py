# ---
# description: Every account your workspace is connected to, from the NoClick app or from code, in one list - each checked with its provider, and the ones that can change things made to ask you before they do.
# card_title: Guard your connected accounts
# card_line: Risky writes wait for your approval.
# mark: shield-check
# cmd: ["python", "08_automations/guard_connected_accounts.py"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # Guard your connected accounts
#
# Accounts get connected in two places: in the NoClick app, by clicking Connect, and from code, as
# named connections. To the SDK they are one list. This example walks it, asks each provider whether
# the account still works, and, with `--guard`, makes every operation that changes something in an
# account you own ask you first: in your code, your agents, and the app's workflows alike.
#
# ```bash
# pip install noclick
# export NOCLICK_API_KEY=nk_live_...
# python 08_automations/guard_connected_accounts.py            # report only
# python 08_automations/guard_connected_accounts.py --guard    # also require approval for writes
# ```

import sys

import noclick

# ## One list
#
# `Connection.list()` returns your named connections first, then the accounts connected in the app.
# `origin` says which is which; an app account's id is `credential:<id>`, which is how you name it in
# `from_id` and in a ref like `"credential:<id>.send_message_to_channel"`. `access` is `owner` for
# your own, `view` or `edit` for one a teammate shared with you.
#
# A model provider (a Claude or ChatGPT key) is a connection too, but it runs no operations: an
# agent thinks with it. `Connection.integrations(kind="model")` names them, so the walk skips them.


def writes(connection: noclick.Connection) -> list:
    """The operations that change something in the account, the ones worth a person's yes."""
    return [op.name for op in connection.operations() if not op.read_only]


# ## Make writes ask first
#
# `require_approval` only ever adds: each call of those operations then waits for the account's
# owner to approve that exact call, wherever it comes from. Lifting one is done in the app. On an
# account shared with you, the rules stay its owner's, so the walk leaves those alone.


def main() -> None:
    guard = "--guard" in sys.argv
    models = {info.name for info in noclick.Connection.integrations(kind="model")}
    for connection in noclick.Connection.list():
        where = "the app" if connection.origin == "app" else "code"
        print(f"{connection.name} ({connection.integration}, connected in {where}, {connection.access})")
        if not connection.connected:
            print(f"  {connection.status}: reconnect it in {where}")
            continue
        check = connection.verify()
        print(f"  {check.message}")
        if connection.integration in models or "*" in connection.approval_operations:
            continue
        unguarded = [name for name in writes(connection) if name not in connection.approval_operations]
        if unguarded and guard and connection.access == "owner":
            connection.require_approval(*unguarded)
            print(f"  now asks you before: {', '.join(unguarded)}")
        elif unguarded:
            print(f"  acts without asking: {', '.join(unguarded)}")


if __name__ == "__main__":
    main()

# ## Clean up
#
# Reading and checking create nothing. A verify asks each provider once and costs nothing at
# NoClick. To let an operation run without asking again, change the account's permissions in the
# NoClick app (Connections).

# NoClick SDK examples

Complete programs built on the [NoClick Python SDK](../python), each one a thing people actually
build: an assistant for every user of your app, a receptionist on a real phone number, a coding
agent that turns issues into pull requests. Every file is also its own guide. The prose lives in
comments beside the code it explains, and the same file renders as a page at
[noclick.com/docs/examples](https://noclick.com/docs/examples).

## Run one

```bash
pip install noclick
export NOCLICK_API_KEY=nk_live_...     # a key from the developer console's API keys
cd sdk/examples
python 01_getting_started/hello_agent.py
```

The header of each file lists what it needs: `env` for environment variables beyond your key, and
`deps` for packages beyond `noclick` (`pip install openai`, say). Nothing else needs editing.

Examples are safe to run twice. They create what they need with `from_name(...,
create_if_missing=True)`, so a second run finds it instead of making another, and each one ends by
saying how to delete what it made and what it costs to keep.

Some examples use parts of the SDK that are designed but not built yet; until they ship, those
calls answer 404, or `not_available` where NoClick has built them and waits on a vendor going live.
The page for each example lists the designed APIs it uses, so you know before you run it.

## The examples

### 01 Getting started

| Example | What you get |
| --- | --- |
| [`hello_agent.py`](01_getting_started/hello_agent.py) | A hosted agent that researches the web with no accounts to connect, a conversation that continues, and the same agent on Claude Code with one more argument. |
| [`connect_a_user.py`](01_getting_started/connect_a_user.py) | Your first user under your own id, their Gmail connected through a link, then read from your code and from their own agent. |
| [`openai_compatible.py`](01_getting_started/openai_compatible.py) | The official OpenAI SDK pointed at NoClick: chat, streaming and embeddings on your NoClick account, and your agents as models, in code or in a chat UI. |

### 02 Agents in your product

| Example | What you get |
| --- | --- |
| [`assistant_for_every_user/`](02_agents_in_your_product/assistant_for_every_user) ★ | An assistant for each of your users, working in their own Gmail and Calendar, in your app's chat. |
| [`support_agent/`](02_agents_in_your_product/support_agent) ★ | One support agent answering on your site's chat, by email and on the phone, with refunds a person approves. |
| [`your_llm_your_users_tools.py`](02_agents_in_your_product/your_llm_your_users_tools.py) | Your own model loop with each user's tools, approvals and connect links included, and the same tools in Claude Desktop and Cursor. |
| [`charge_your_users.py`](02_agents_in_your_product/charge_your_users.py) | Prepaid credits on your own Stripe: usage comes off each user's balance as it happens, they're paused with a top-up link when it runs low, and what they sent meanwhile runs once they pay. |

### 03 Voice and email

| Example | What you get |
| --- | --- |
| [`phone_receptionist.py`](03_voice_and_email/phone_receptionist.py) ★ | A real phone number that answers like a front desk, books into your Google Calendar, texts callers a confirmation and puts the hard calls through to you. |
| [`accounts_payable_inbox.py`](03_voice_and_email/accounts_payable_inbox.py) ★ | An accounts-payable clerk with its own email address: it checks each invoice against your books, gets a person's approval over a limit, pays with a single-use card and replies to the vendor. |
| [`one_assistant_every_channel.py`](03_voice_and_email/one_assistant_every_channel.py) | Your own agent answering what you text NoClick on WhatsApp or iMessage, your email and your calls, in one conversation your code can join. |

### 04 Coding agents

| Example | What you get |
| --- | --- |
| [`issue_to_pull_request.py`](04_coding_agents/issue_to_pull_request.py) ★ | Label a GitHub issue and Claude Code reproduces the bug, fixes it, runs your tests and opens a pull request. |
| [`prompt_to_deployed_app.py`](04_coding_agents/prompt_to_deployed_app.py) ★ | Your users describe an app, a coding agent builds it, and it goes live on your domain with the database, email and payments it needs. |

### 05 Scaling out

| Example | What you get |
| --- | --- |
| [`lead_enrichment_at_scale.py`](05_scaling_out/lead_enrichment_at_scale.py) | Ten thousand leads researched by ten agents working one queue, and the results sent to your CRM. |

### 06 Multi-agent

| Example | What you get |
| --- | --- |
| [`newsletter_that_runs_itself/`](06_multi_agent/newsletter_that_runs_itself) | A room of agents that research, write and edit a weekly newsletter, published once a person approves it. |
| [`ops_assistant.py`](06_multi_agent/ops_assistant.py) | An agent that runs your NoClick account, buying a phone number once you approve it, and a read-only one that answers questions about a file you send it. |

### 07 Data and browsers

| Example | What you get |
| --- | --- |
| [`sales_call_search.py`](07_data_and_browsers/sales_call_search.py) ★ | Ask your sales calls anything: recordings transcribed, indexed and answered with citations. |
| [`vendor_portal_downloads.py`](07_data_and_browsers/vendor_portal_downloads.py) | A browser agent that signs in to vendor portals with no API and collects the files you need. |

### 08 Automations

| Example | What you get |
| --- | --- |
| [`automation_health_check.py`](08_automations/automation_health_check.py) | A morning check of every automation you own: what isn't set up, the step that broke in its last failed run, and a pause for the ones failing over and over. |
| [`guard_connected_accounts.py`](08_automations/guard_connected_accounts.py) | Every account connected in the app or from code, in one list, each checked with its provider, and the ones that can change things made to ask you first. |
| [`daily_digest_routine.py`](08_automations/daily_digest_routine.py) | A weekday digest posted to Slack from one long conversation, so each morning builds on the last, through the Slack account you connected in the app. |
| [`change_an_automation.py`](08_automations/change_an_automation.py) | A Slack post added to the end of an automation built in the app, in one change that lands only if nobody edited it meanwhile, and an undo from its versions. |

★ marks the featured examples, shown first on the docs site.

## Write one

An example is one `.py` file, or a folder whose `main.py` is the page with any other files (a React
component, say) beside it. It starts with a header the docs site reads:

```python
# ---
# description: One sentence for the gallery card: what you get, not how.
# cmd: ["python", "03_voice_and_email/phone_receptionist.py"]
# env: ["NOCLICK_API_KEY"]
# deps: []
# ---

# # An AI receptionist on a real phone number
#
# Prose in Markdown, in comment blocks between the code. Say why each step is there
# and what the reader gets.

import noclick
```

- `cmd` runs the file from this folder, and the first `# #` line is its title.
- Comment blocks at the top level are the page's prose; comments inside code stay in the code.
- Write in the docs' voice: plain, second person, short sentences.
- Use the real `noclick` API, and a NoClick primitive only where the build needs it.
- Make it complete and runnable: a `main()`, secrets from environment variables, safe to run twice,
  and a last section on cleaning up.

Before you open a pull request, check it compiles and lints:

```bash
python3 -m py_compile 01_getting_started/hello_agent.py
ruff check 01_getting_started/hello_agent.py
```

Once the pull request is applied, the docs site checks every `noclick` name and attribute the
example uses against the real client before it shows the example, so use only what the SDK has.

# Local agent processes

A running conversation owns one CLI process, scoped by workflow, agent node,
and conversation key. New messages with the same scope enter that live process.
Different scopes run concurrently. An absent or empty key starts a separate
conversation and workspace for each invocation.

| Harness | Input transport | Completion ownership |
| --- | --- | --- |
| Codex | App Server `turn/start` / `turn/steer` | Native turn ID |
| Claude Code | Streaming JSON input with replay acknowledgements | Consumed input UUIDs; several queued inputs may share one result |
| OpenCode | Concurrent synchronous session message requests | Assistant parent message ID |
| Hermes | Runs API and run steering | Input receipts, including explicitly unconsumed guidance |
| OpenClaw | Gateway `chat.send` with `queueMode=steer` | Transcript steering target and run completion |

Steering takes effect at the boundaries supported by the harness. Claude may
combine follow-ups into a subsequent turn. Each native result propagates once;
other inputs covered by that result return `skipped` instead of running downstream
nodes again. A lost acknowledgement is never treated as permission to replay work.

Changing credentials, tools, model, or system instructions waits for the current
process to become idle before replacing it. Saved native conversation IDs resume
after process restarts. Codex and Claude retain history in the selected CLI profile;
keep that profile directory stable for an existing conversation. Moving between
operator and attached subscription profiles is not a history migration. MCP access
expires with the process, and each tool call retains the active input's execution
context.

`NOCLICK_LOCAL_AGENT_IDLE_TIMEOUT` controls idle cleanup (default 60 seconds).
`NOCLICK_LOCAL_HARNESS_TIMEOUT` bounds an invocation (default 900 seconds).
Cancelling one caller leaves other accepted inputs running. Cancelling every
caller, process failure, or a timeout stops the process. On POSIX, shutdown also
terminates its tool subprocess group.

The registry belongs to one backend process. Use a single backend worker; multiple
local agents already run as independent child processes. Supporting multiple
backend workers would require explicit conversation affinity and ownership.

Regression tests use real subprocess protocol peers. The opt-in native suite uses
the installed CLIs with a local scripted provider, without paid model calls:

```sh
python backend/tests/fixtures/install_clis.py /tmp/noclick-test-clis
PYTHONPATH=backend PATH="/tmp/noclick-test-clis/bin:$PATH" NOCLICK_TEST_LOCAL_CLIS=1 \
  python -m pytest backend/tests/test_local_harness_native.py
```

Use the pinned CLI versions in `config/_cli_models.json`. Gateway integrations
require Hermes v2026.8.31 and OpenClaw 2026.9.1 or newer; OpenClaw also needs a
compatible Node.js release. The CI installer expects Node.js 24.15 or newer.

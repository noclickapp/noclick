# Contributing to NoClick

Thanks for being here. This guide covers getting a working checkout, the two
most common contributions, and the conventions this codebase enforces.

If anything here is wrong or missing, that's a bug worth reporting —
[Discord](https://discord.com/invite/sHC2mrnss8) is the fastest way to ask.

## Sign your commits

Every commit needs a `Signed-off-by` line. `git commit -s` adds it, and it means
you agree to the [Developer Certificate of Origin](https://developercertificate.org/):
that you wrote the change, or have the right to submit it under this project's
licence.

```
Signed-off-by: Your Name <you@example.com>
```

It is not a copyright assignment and it does not transfer anything — it is a
statement that you are entitled to contribute what you are contributing.
You retain copyright in your work. By submitting it for inclusion, you agree
that NoClick may distribute your contribution under the same Sustainable Use
License that applies to the project, and you license recipients accordingly as
a licensor of that contribution. Do not submit code you cannot license on those
terms.
`git config alias.ci "commit -s"` makes it the default. CI checks each commit in
a pull request, and `git rebase --signoff main` fixes a branch that predates it.

## Setup

Prerequisites: Docker, the [Supabase CLI](https://supabase.com/docs/guides/cli),
Python 3.12 (3.13 isn't supported — some pinned wheels don't build on it), and
Node.js 20 or newer with pnpm 10.34.4.

```bash
pip install -r requirements.txt
make local
```

That starts a local Supabase, applies migrations, and runs both processes.
Sign up with any email — local auth confirms instantly.

Details, environment variables, and how to connect model providers and OAuth
apps: **[docs/self-hosting.md](./docs/self-hosting.md)**.

## Adding an integration node

The most useful contribution, and the least code. The editor UI is generated
from your Pydantic model, so you write Python and the interface appears.

1. Copy the closest existing node in `backend/nodes/` — one with the same auth
   style (API key vs OAuth) and a similar operation shape.
2. Define operations as Pydantic config models. Field metadata drives the UI:
   see the schema-extension table in [CLAUDE.md](./CLAUDE.md).
3. Register the node in `backend/nodes/core/registry.py`.
4. Regenerate schemas: `cd backend && python scripts/generate_socket_types.py`
   (the pre-commit hook does this too).
5. Add tests under `backend/nodes/tests/`. Mock the provider's HTTP calls —
   tests must not need real credentials.

For OAuth nodes, declare the scopes each operation needs in
`backend/nodes/scopes/<provider>.py` and point the node at that registry.
`backend/tests/test_oauth_scope_coverage.py` enforces it: a node that requests a
scope it never uses, or uses one it never requested, fails CI. Adding a scope
forces every existing user to re-authorize, so treat scope changes as migrations
rather than edits.

## Adding a socket event or handler

1. Define the event as a Pydantic model in `backend/wss/sender/events.py`.
2. Route it in `backend/wss/receiver/event_routing.py`.
3. Implement the handler in `backend/wss/handlers/`.
4. Regenerate types so the frontend sees it.

Always send through `send_event()` with a typed model — never a bare
`sio.emit()`.

## Tests

```bash
make test-backend-community
make check-community-boundary
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend typecheck
pnpm --dir frontend build
pnpm --dir frontend test
```

Focused tests are fine while iterating; the backend suite, boundary gate,
whole-tree TypeScript check, production build, and frontend suite should all
pass before you open a PR. A few structural tests are worth knowing because they
fail in ways that look confusing at first:

| Test | What it protects |
|---|---|
| `scripts/check-repository-transport.py` | Current and historical content cannot hide behind a submodule, archive, LFS pointer, nested Git store, or unsafe symlink |
| `test_no_dangling_imports.py` | Every first-party import resolves — catches deferred imports that a boot check can't |
| `test_oauth_scope_coverage.py` | Requested OAuth scopes match what the code actually calls |
| `test_config_unset_marker_guard.py` | Every node's defaulted fields survive empty values |

If one fails, it's usually pointing at something real rather than being
pedantic. Ask if the message isn't clear.

## Conventions worth internalizing

- **No fallbacks.** Fail loudly rather than degrading silently. A default that
  "happens to work" is how a broken config reaches production looking healthy.
- **Reuse before adding.** Generalize the existing helper instead of writing a
  near-duplicate.
- **Never edit a test to get past something you don't understand.** Work out
  what the code does first.
- **Comment the why**, not the what.
- Match the surrounding code's naming, density, and idiom.

## Changing the database schema

`infra/supabase/migrations/` here is not the monorepo's migration history. It is
a squashed initial schema plus the migrations added since, and the export
reproduces it — so **a migration file added in a pull request to this repository
is replaced by the next re-sync**, along with everything else under that
directory.

That is not a reason to avoid schema work; it is a reason to raise it as an
issue first. A maintainer lands the migration in the monorepo and it arrives
here on the next export, in the same shape you proposed. What does not survive
is a migration authored only here.

The same holds for anything else the export produces, which is most of the tree.
Where a file is edition-specific — a different implementation on each side —
the export keeps both, and a maintainer will say so on the issue.

## Working with coding agents

[CLAUDE.md](./CLAUDE.md) (symlinked as `AGENTS.md`) carries the architecture and
conventions in the form agents read, and `.claude/skills/` has task-specific
guides — adding a node, adding a handler, writing handler tests, building custom
interface components. Pointing Claude Code or Codex at a checkout should produce
changes that fit the codebase rather than plausible-looking ones. If an agent
gets something consistently wrong, improving those files is a genuinely useful PR.

## Pull requests

- One concern per PR; a focused diff gets reviewed faster.
- Say what you verified and how. "Tests pass" is weaker than "ran the workflow
  end to end on a local install and the trigger fired twice".
- Regenerated files (schemas, socket types) belong in the same commit as the
  change that caused them.

## License

Contributions are accepted under the repository's
[Sustainable Use License 1.0](./LICENSE.md), and signing off a commit is how you
say you may submit them under it — see [Sign your commits](#sign-your-commits).

The licence is source-available rather than open source, which is worth knowing
before you spend an evening on a change: it permits internal and non-commercial
use, and it does not convert to a permissive licence over time.

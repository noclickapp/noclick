# DB access — the rules and the repository pattern

This document is the source of truth for how backend code accesses Postgres.
A pool acquisition must pin a physical connection and a transaction context
must provide real BEGIN/COMMIT/ROLLBACK semantics. The implementation uses one
native `asyncpg.Pool` on the main event loop.

## The surface

One pool per process, owned by `app_lifespan` (created via
`utils.database_pool.init_native_pool()` at startup, closed at shutdown).
Access it one of three ways:

- `pool = await self.get_pool()` from any `DatabasePoolMixin` subclass, or
  `from utils.database_pool import get_native_pool` elsewhere. Both return
  the real `asyncpg.Pool` and RAISE if the pool is uninitialized or bound to
  another event loop — pool lifecycle belongs to `app_lifespan` (prod) and
  `ensure_native_db_pool` in `tests/conftest.py` (tests); nothing else may
  close or re-create it.
- Pool-level verbs (`pool.fetch/fetchrow/fetchval/execute/executemany`) for
  one-shot statements.
- `async with pool.acquire() as conn:` for multi-statement units of work —
  every statement in the block runs on the same physical connection, and
  `async with conn.transaction():` is a real BEGIN/COMMIT/ROLLBACK.

There is no sync surface and no worker-thread bridge. Code running off the
loop must hand DB work to the loop (`asyncio.run_coroutine_threadsafe`), not
reach for the pool.

## The rules

1. **One connection per unit of work.** `async with pool.acquire() as conn:`
   for multi-statement work; a pool-level verb for one-shots. Don't open an
   acquire block for a single statement.
2. **The acquire block IS the unit of work.** Using `conn` after the block
   exits raises `InterfaceError: connection has been released` — that error
   means restructure, not retry.
3. **Multi-write sequences get a real transaction.** If a handler runs two or
   more dependent writes, wrap them in `async with conn.transaction():` — a
   mid-sequence failure must roll back, never strand half the writes (see
   `organization_handler.create_organization` for the pattern). Don't nest
   transactions; restructure instead.
4. **SQL lives in a repository**, not inline in the handler. See
   `repositories/usage.py` for the reference implementation and
   "Repository pattern" below.
5. **Never await non-DB work inside an acquire block.** External HTTP (R2,
   Cloudflare, provider APIs, webhook relays), CAS reads, big serialization —
   all of it runs before the acquire or after the release. A pinned
   connection held across a slow HTTP call is exactly how the pool starves.
   (`utils/cas/gc.py:phase_b_orphan_sweep` is the ONE sanctioned exception —
   its in-transaction R2 delete is load-bearing against a dedupe race and it
   runs on the cron container's private pool; the comment there explains.)
6. **Fire-and-forget writes are explicit at the call site.** Use
   `spawn(pool.execute(...))` (from `utils.async_helpers`) with a one-line
   comment saying the durability tradeoff is deliberate. There is no `wait=`
   flag anywhere — if you await it, it's durable; if you spawn it, it's not.
7. **Layered timeouts.** Client-side `asyncio.timeout` around the unit of
   work; the pool's `command_timeout` (30s) covers server-side cancel. Both
   matter — asyncpg's timeout only fires while awaiting the socket.
8. **Never read `POSTGRES_POOLER_URL`/`POSTGRES_URL` directly.** Go through
   `get_runtime_database_url()` + `get_asyncpg_connect_kwargs()` (PgBouncer
   needs `statement_cache_size=0`). No fallback between the two URLs — a
   deploy-config gap must fail loudly.
9. **Instrument the pool, not just the queries.**
   `utils.database_pool.get_pool_status()` returns
   `{size, idle_size, max_size, is_closing}`, shipped on every
   `container.health` span — see "Pool telemetry".

## Repository pattern — the concrete shape

Every repo:

- One file per bounded domain in `backend/repositories/`.
- Constructor: `def __init__(self, pool): self._pool = pool`.
- Public methods are `async def` and return typed values (dataclass /
  `dict[str, T]` / `list[T]`). Never leak `asyncpg.Record`.
- SQL is a module/class-level `_SNAKE_UPPER_SQL` constant when non-trivial.
- Multi-statement writes wrap `acquire()` + `conn.transaction()`; methods
  that must compose into a caller-owned transaction take an explicit `conn`
  first argument instead (OrgRepo style) — in that case the HANDLER owns the
  `conn.transaction()` boundary and must actually open it.
- Any interpolation of identifiers (column names, `date_trunc` grains) MUST
  be gated by an allowlist frozenset inside the repo — see
  `UsageRepo._ALLOWED_DATE_TRUNC`.
- **Security predicates are defined once.** Org membership + primary-org
  SQL live in `repositories/organization.py`; the credential access
  predicate lives in `repositories/credentials.py`; workflow-owner
  resolution lives in `repositories/workflow.py` (with an explicit
  `include_deleted` policy switch). Other repos and `utils/` helpers import
  those, never re-declare them — a predicate that exists twice WILL drift,
  and drift in an access predicate is an authorization bug.

### Checklist for migrating a handler

1. Identify the SQL in the handler.
2. Create or extend the domain's repo; move the SQL there.
3. Handler: `repo = FooRepo(await self.get_pool())`, call typed methods.
4. Add a test in `tests/repositories/` against local Postgres.
5. Update the status table below.

## Migration status

**13 repositories built, 15+ handlers migrated (2026-07-01).**

| Handler | Repo(s) |
|---|---|
| `usage_dashboard_handler` | `UsageRepo` |
| `analytics_handler` | `AnalyticsRepo` |
| `share_handler` | `ShareRepo` |
| `workflow_handler`, `workflow_mcp_handler`, `workflow_execution_handler`, `workflow_checkpoint_handler` | `WorkflowRepo` |
| `workflow_builder_handler` | `WorkflowRepo`, `ConversationRepo`, `SkillRepo` |
| `agent_handler` | `ConversationRepo` |
| `organization_handler`, `folder_handler` | `OrgRepo` |
| `credentials_handler` | `CredentialsRepo` |
| `resource_handler` | `ResourceRepo` |
| `skill_handler` | `SkillRepo` |
| `saved_output_handler` | `SavedOutputRepo` |
| `feed_handler` | `FeedRepo` |
| `publish_handler` | `PublishRepo` |

Deliberately inline (small SQL surface; `pool.acquire()` inline is cleaner
than a one-method repo): `onboarding_handler`, `feedback_handler`,
`debug_handler`, `ypy_handler`, `setup_execution_handler`.

Deliberately deferred: `billing/plan_limits.py:get_credit_usage` (takes
`conn`, called mid-transaction) and `billing/usage_tracker.py` read paths
(coupled to the topup ledger CTE; the INSERT stays in `billing/schema.py`).

## Pool telemetry

Every `container.health` span (3s cadence) carries:

| attribute           | source                         | reads as |
|---                  |---                             |---       |
| `db.pool.size`      | `asyncpg.Pool.get_size()`      | conns physically open |
| `db.pool.idle_size` | `asyncpg.Pool.get_idle_size()` | conns available now |
| `db.pool.max_size`  | `asyncpg.Pool.get_max_size()`  | capacity (30) |

**Idle-conn depletion** is the alert worth having: `MAX(db.pool.idle_size)
GROUP BY service.instance.id` pinned at 0 for > 30s means every slot is checked
out — the ~30s warning before waiting acquires start timing out at
`_POOL_ACQUIRE_TIMEOUT=10`. The composite utilization ratio
`(size - idle_size) / max_size` at 100% for > 60s is cascade territory.

## What NOT to do

- **Don't hold a conn across HTTP or long CPU work** (rule 5). Release and
  re-acquire around the slow part.
- **Don't nest transactions.** One txn per acquire.
- **Don't re-declare an access predicate.** Import it from its owning repo.
- **Don't add ORMs.** Raw asyncpg + repositories keep query plans explicit and
  reviewable.
- **Don't build a second pool.** `get_cas_pool` was folded into the native
  pool; maintenance processes that cannot run the application lifespan
  build one short-lived pool inside the job; that is the only sanctioned
  second-pool shape.

## Design rationale

A native `asyncpg.Pool` keeps acquisition and transaction semantics honest: an
acquire block visibly holds one physical connection, and a transaction context
provides real atomicity. That visibility makes the no-I/O-inside-acquire rule
enforceable.

"""Repository layer — the greenfield pattern for DB access.

A repository is a small class that owns the SQL for one domain object (or a
tight group of related ones) and exposes typed async methods to handlers.
Handlers stop assembling SQL inline; they instantiate a repo with the pool
proxy and call typed methods. Benefits:

  1. SQL is greppable in one file per domain — no more hunting through 50
     handlers for a query touching some table.
  2. Perf regressions have a place to live — a repository method with an
     ``EXPLAIN``-verified query plan is a stable contract.
  3. Handlers become shorter and read like intent rather than SQL glue.
  4. Test-time mocking is trivial — swap the repo class.

Rules for adding a new repository:

  - One file per bounded domain (usage, credentials, workflows, ...).
  - Constructor takes ``pool`` — the native ``asyncpg.Pool`` from
    ``DatabasePoolMixin.get_pool()`` / ``get_native_pool()``.
  - Method contract: return typed values (dataclass / dict[str, T] / list[T]).
    Callers should never see raw ``asyncpg.Record`` types across the boundary
    because they hide the row shape.
  - Use ``async with self._pool.acquire() as conn:`` for reads; use
    ``async with conn.transaction():`` for multi-statement writes so the
    real-transaction guarantee (fixed 2026-07-01) is engaged.

See ``backend/utils/DB_MIGRATION.md`` for the full migration checklist.
"""

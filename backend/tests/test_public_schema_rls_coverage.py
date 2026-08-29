"""Every table in `public` is reachable through PostgREST, so every table needs
a reason it is safe.

The schema grants the API roles blanket table privileges and leans on row-level
security to decide who sees what. That is a sound arrangement exactly as long as
RLS is on. A table without it inherits the grant and nothing else:
`local_cron_schedules` shipped that way and exposed every user's webhook
capability URLs, plus an insert that made the scheduler POST wherever the author
liked.

The per-table tests next to this one check specific tables people thought about.
This one checks the ones nobody thought about, which is where that bug came from.
"""

import pytest


# Tables deliberately readable or writable by the API roles under a policy.
# Adding a name here is a decision about who can read the rows; make it
# consciously, and only for a table whose policies you have read.
API_REACHABLE = {
    "resource_shares",  # SELECT only; writes revoked, backend checks ownership
}

# These tables contain cross-tenant execution state and are reachable only via
# backend repositories. A USING(true) API-role policy on any of them is an
# authorization bypass even though RLS is technically enabled.
BACKEND_ONLY = {
    "activity_logs",
    "approval_requests",
    "cas_blobs",
    "cas_manifests",
    "cas_refs",
    "cas_storage_stats",
    "instance_provider_keys",
    "workflow_run_totals",
}


@pytest.mark.asyncio
async def test_every_public_table_has_rls_enabled(postgres_db):
    """No table may rely on the blanket grant alone."""
    rows = await postgres_db.fetch(
        """
        SELECT c.relname
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relkind = 'r'
           AND NOT c.relrowsecurity
         ORDER BY c.relname
        """
    )
    unprotected = [r["relname"] for r in rows]
    assert not unprotected, (
        "These tables have row-level security disabled while the schema grants the\n"
        "API roles table privileges, so any signed-in user can read and write them\n"
        "through PostgREST:\n  " + "\n  ".join(unprotected) + "\n\n"
        "Enable RLS. If the table is backend-only, that is all it needs — no policy\n"
        "means no rows — and revoking the grants as well makes it fail closed twice."
    )


@pytest.mark.asyncio
async def test_tables_without_policies_have_no_api_grants(postgres_db):
    """A table with RLS and no policies is backend-only by construction. Leaving
    the grant on it is harmless today and one accidental policy away from not
    being, so the grant goes too."""
    rows = await postgres_db.fetch(
        """
        SELECT c.relname
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relkind = 'r'
           AND c.relrowsecurity
           AND NOT EXISTS (
                 SELECT 1 FROM pg_policies p
                  WHERE p.schemaname = 'public' AND p.tablename = c.relname
           )
         ORDER BY c.relname
        """
    )
    leaky = []
    for row in rows:
        table = row["relname"]
        if table in API_REACHABLE:
            continue
        for role in ("anon", "authenticated"):
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                granted = await postgres_db.fetchval(
                    "SELECT has_table_privilege($1, $2, $3)",
                    role, f"public.{table}", priv,
                )
                if granted:
                    leaky.append(f"{table}: {priv} still granted to {role}")
    assert not leaky, (
        "Backend-only tables (RLS on, no policies) still carry API-role grants:\n  "
        + "\n  ".join(leaky)
    )


@pytest.mark.asyncio
async def test_backend_only_tables_have_no_api_role_policies_or_grants(postgres_db):
    """RLS-on is not enough when a policy grants every signed-in user every row."""
    policies = await postgres_db.fetch(
        """
        SELECT tablename, policyname, roles
          FROM pg_policies
         WHERE schemaname = 'public'
           AND tablename = ANY($1::text[])
           AND roles && ARRAY['anon', 'authenticated']::name[]
         ORDER BY tablename, policyname
        """,
        sorted(BACKEND_ONLY),
    )
    assert not policies, (
        "Backend-only tables expose PostgREST policies to API roles:\n  "
        + "\n  ".join(
            f"{row['tablename']}: {row['policyname']} -> {list(row['roles'])}"
            for row in policies
        )
    )

    grants = []
    for table in sorted(BACKEND_ONLY):
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if await postgres_db.fetchval(
                    "SELECT has_table_privilege($1, $2, $3)",
                    role,
                    f"public.{table}",
                    privilege,
                ):
                    grants.append(f"{table}: {privilege} granted to {role}")
    assert not grants, "Backend-only tables retain API grants:\n  " + "\n  ".join(grants)

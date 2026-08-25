"""A policy that reads its own table is a cycle, and Postgres refuses the query.

`organization_members` had four such policies. Reading the table as a signed-in
user returned `42P17 infinite recursion detected in policy for relation
"organization_members"` — and so did reading anything whose own policy consults
it, which is `organizations`, `organization_invites`, `workflow_folders` and
`resource_shares`. The last of those is one of only two tables the browser reads
directly, so this was not a hypothetical.

Nothing in the application noticed, because the one code path that touches those
tables uses the service role, which bypasses RLS entirely. It would have been
found by the first person to use the API the schema exposes.

The fix asks the question through a SECURITY DEFINER function instead, whose body
is not policy-checked. These tests pin both halves: the rule, and the behaviour.
"""

import pathlib

import pytest


# Tables whose policies must survive being read as a signed-in user. auth.uid()
# is NULL in this fixture, so the rows come back empty — the assertion is that
# the query answers at all.
API_READABLE = ("organization_members", "organizations", "resource_shares", "workflow_folders")


def _shipped_claim_accessors() -> str:
    """The auth.uid() family as the installer writes it (docker/bootstrap.py)."""
    import importlib.util

    path = pathlib.Path(__file__).resolve().parents[2] / "docker" / "bootstrap.py"
    spec = importlib.util.spec_from_file_location("noclick_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CLAIM_ACCESSORS


@pytest.mark.asyncio
@pytest.mark.parametrize("table", API_READABLE)
async def test_reading_as_authenticated_does_not_recurse(postgres_db, table):
    async with postgres_db.transaction():
        await postgres_db.execute("SET LOCAL ROLE authenticated")
        # Raises asyncpg.InfiniteRecursionError (42P17) if a policy reads its own
        # table; returns [] once it does not.
        rows = await postgres_db.fetch(f"SELECT 1 FROM public.{table} LIMIT 1")
        assert rows == []


# Empty, and meant to stay that way: a policy that reads its own table has no
# working form. The one entry this held was "Creator can add self as owner",
# which is now asked through a SECURITY DEFINER function like the rest.
KNOWN_SELF_READING: set = set()


@pytest.mark.asyncio
async def test_no_policy_reads_its_own_table(postgres_db):
    """The general rule, because the four that broke were not special.

    A policy may consult another table freely — that just nests one policy check
    inside another. Reading its OWN table is the cycle. Qualifying a column of
    the row under check (`workflow_folders.organization_id`) is not a read and is
    fine; appearing after FROM or JOIN is.
    """
    rows = await postgres_db.fetch(
        """
        SELECT tablename, policyname
          FROM pg_policies
         WHERE schemaname = 'public'
           AND (coalesce(qual, '') || ' ' || coalesce(with_check, ''))
               ~ ('(FROM|JOIN)[[:space:]]+' || tablename || '([^a-z_]|$)')
         ORDER BY tablename, policyname
        """
    )
    offenders = [
        f"{r['tablename']}: {r['policyname']}"
        for r in rows
        if (r["tablename"], r["policyname"]) not in KNOWN_SELF_READING
    ]
    assert not offenders, (
        "These policies read the table they guard, which Postgres rejects as\n"
        "infinite recursion the moment anyone reads it through the API:\n  "
        + "\n  ".join(offenders)
        + "\n\nMove the lookup into a SECURITY DEFINER function (see\n"
        "public.user_organization_ids)."
    )


@pytest.mark.asyncio
async def test_org_lookup_helpers_are_definer_and_narrow(postgres_db):
    """SECURITY DEFINER is only safe here because the functions take no arguments
    and answer solely about auth.uid(). A parameter would turn either of them
    into a way to read another person's memberships."""
    rows = await postgres_db.fetch(
        """
        SELECT p.proname, p.prosecdef, p.pronargs, p.provolatile
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.proname IN ('user_organization_ids', 'user_admin_organization_ids')
        """
    )
    assert len(rows) == 2, f"both helpers must exist, found {[r['proname'] for r in rows]}"
    for row in rows:
        assert row["prosecdef"], f"{row['proname']} must be SECURITY DEFINER to break the cycle"
        assert row["pronargs"] == 0, (
            f"{row['proname']} takes an argument — a SECURITY DEFINER function that "
            f"answers about anyone but the caller is a way to read their data"
        )
        assert row["provolatile"] in ("s", b"s"), f"{row['proname']} should be STABLE"


@pytest.mark.asyncio
async def test_only_a_memberless_organization_can_be_claimed(postgres_db):
    """"Creator can add self as owner" is how a browser makes itself the owner
    of an organization it has just created, and the window it opens is the
    decision this policy embodies: anyone signed in can claim ANY organization
    that currently has no members, because the organization id comes from the
    request.

    That window is narrow by construction. An organization loses its last member
    only if its owner leaves, and no policy permits that — "Members can leave
    org" and "Admins can remove members" both exclude the owner row. So a
    memberless organization is one nobody has joined yet, which is exactly the
    case this exists for.

    The three refusals below are the boundary: someone else's row, a different
    role, and an organization that already has anyone in it.
    """
    # The fixture stubs auth.uid() to return NULL, so no identity-dependent
    # policy can be satisfied against it. Install the accessors the install
    # actually ships — the ones in docker/bootstrap.py — so this exercises them
    # too rather than a copy that can drift.
    await postgres_db.execute(_shipped_claim_accessors())

    claimer = "11111111-1111-1111-1111-111111111111"
    other = "22222222-2222-2222-2222-222222222222"
    empty_org = "aaaaaaaa-1111-1111-1111-111111111111"
    taken_org = "bbbbbbbb-2222-2222-2222-222222222222"
    # A third, still untouched: once empty_org is claimed it is neither
    # memberless nor free of the claimer, and a unique constraint would refuse
    # the shape checks below before any policy got to.
    fresh_org = "cccccccc-3333-3333-3333-333333333333"

    async def insert(conn, org, user, role):
        await conn.execute(
            "INSERT INTO organization_members (organization_id, user_id, role) VALUES ($1, $2, $3)",
            org, user, role,
        )

    async with postgres_db.transaction():
        for uid, email in ((claimer, "claimer@example.test"), (other, "other@example.test")):
            await postgres_db.execute(
                "INSERT INTO auth.users (id, email) VALUES ($1, $2)", uid, email
            )
        await postgres_db.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Empty', 'empty-probe')", empty_org
        )
        await postgres_db.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Taken', 'taken-probe')", taken_org
        )
        await postgres_db.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Fresh', 'fresh-probe')", fresh_org
        )
        await insert(postgres_db, taken_org, other, "owner")  # as the backend does

        await postgres_db.execute(
            "SELECT set_config('request.jwt.claims', $1, true)",
            '{"sub": "' + claimer + '", "role": "authenticated"}',
        )
        await postgres_db.execute("SET LOCAL ROLE authenticated")

        # Allowed: myself, as owner, of an organization nobody is in.
        async with postgres_db.transaction():
            await insert(postgres_db, empty_org, claimer, "owner")

        for description, org, user, role in (
            ("an organization that already has a member", taken_org, claimer, "owner"),
            ("somebody else's membership", fresh_org, other, "owner"),
            ("a role other than owner", fresh_org, claimer, "admin"),
        ):
            with pytest.raises(Exception) as caught:  # noqa: PT011 - any refusal will do
                # A savepoint, so one refusal does not abort the setup.
                async with postgres_db.transaction():
                    await insert(postgres_db, org, user, role)
            assert "policy" in str(caught.value).lower(), (
                f"{description} was refused for the wrong reason: {caught.value}"
            )

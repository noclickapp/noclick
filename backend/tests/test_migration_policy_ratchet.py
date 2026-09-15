"""No migration may leave an allow-all RLS policy open to the PostgREST roles.

Supabase's advisor only flags tables with RLS OFF. A table with RLS ON and a
``USING (true)`` policy for ``anon``/``authenticated`` — or with no ``TO``
clause, which means ``public`` — is just as exposed through the public key, and
that is what leaked every ``cas_blobs`` row and let anon delete
``cas_manifests`` until 2026-09-15. Backend-only tables need no policy at all:
the backend connects as ``postgres`` and ``service_role`` bypasses RLS.

The scan replays every ``CREATE POLICY``/``DROP POLICY`` in migration order, so
a historical offender that a later migration drops is fine; only policies that
survive the whole series are judged. In the open tree the same path holds the
override migrations, so both editions are checked by the one test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIRS = [
    d
    for d in (
        REPO / "infra" / "supabase" / "migrations",
        REPO / "oss" / "overrides" / "infra" / "supabase" / "migrations",
    )
    if d.is_dir()
]

API_ROLES = {"anon", "authenticated", "public"}

# Deliberate world-readable rows (template gallery, fork counts, vote tallies).
# Shrink-only: a new public SELECT needs a review, not a line here.
ALLOWED_PUBLIC_READS = {
    ("resource_forks", "Anyone can view fork relationships"),
    ("template_votes", "template_votes_public_read"),
    ("workflow_templates", "workflow_templates_public_read"),
}

_NAME = r'(?:"(?P<qname>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))'
_TABLE = r"(?:public\.)?(?P<table>%I|[A-Za-z_][A-Za-z0-9_]*)"
_CREATE = re.compile(
    r"CREATE\s+POLICY\s+" + _NAME + r"\s+ON\s+" + _TABLE + r"(?P<body>.*?)(?:;|'\s*,)",
    re.IGNORECASE | re.DOTALL,
)
_DROP = re.compile(
    r"DROP\s+POLICY\s+(?:IF\s+EXISTS\s+)?" + _NAME + r"\s+ON\s+" + _TABLE,
    re.IGNORECASE,
)
_DROP_TABLE = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _TABLE, re.IGNORECASE)
# A plpgsql loop stamping one policy onto several tables: `FOREACH t IN ARRAY ARRAY['a', 'b'] LOOP ... format('... ON public.%I ...', t)`.
_ARRAY = re.compile(r"ARRAY\s*\[([^\]]*)\]", re.IGNORECASE)
_FOR = re.compile(r"\bFOR\s+(ALL|SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_TO = re.compile(r"\bTO\s+([A-Za-z_,\s]+?)\s*(?=\bUSING\b|\bWITH\s+CHECK\b|$)", re.IGNORECASE | re.DOTALL)
_USING_TRUE = re.compile(r"\bUSING\s*\(\s*true\s*\)", re.IGNORECASE)
_CHECK_TRUE = re.compile(r"\bWITH\s+CHECK\s*\(\s*true\s*\)", re.IGNORECASE)
_COMMENT = re.compile(r"--[^\n]*")


def _tables_for(m: re.Match, text: str) -> list[str]:
    table = m.group("table").lower()
    if table != "%i":
        return [table]
    arrays = list(_ARRAY.finditer(text, 0, m.start()))
    assert arrays, f"cannot resolve the tables of a dynamic policy: {m.group(0)[:80]!r}"
    return [t.lower() for t in re.findall(r"'([A-Za-z_][A-Za-z0-9_]*)'", arrays[-1].group(1))]


def _surviving_policies(migration_dir: Path) -> dict[tuple[str, str], tuple[str, str]]:
    """(table, policy) -> (migration file, policy body) after replaying the series."""
    live: dict[tuple[str, str], tuple[str, str]] = {}
    for path in sorted(migration_dir.glob("*.sql")):
        text = _COMMENT.sub("", path.read_text())
        events = [(m.start(), "drop", m) for m in _DROP.finditer(text)]
        events += [(m.start(), "create", m) for m in _CREATE.finditer(text)]
        events += [(m.start(), "drop_table", m) for m in _DROP_TABLE.finditer(text)]
        for _, kind, m in sorted(events, key=lambda e: e[0]):
            if kind == "drop_table":
                for key in [k for k in live if k[0] == m.group("table").lower()]:
                    del live[key]
                continue
            for table in _tables_for(m, text):
                key = (table, m.group("qname") or m.group("name"))
                if kind == "drop":
                    live.pop(key, None)
                else:
                    live[key] = (path.name, m.group("body"))
    return live


def _open_to_api_roles(body: str) -> bool:
    to = _TO.search(body)
    roles = {r.strip().lower() for r in to.group(1).split(",")} if to else {"public"}
    if not roles & API_ROLES:
        return False
    cmd = (_FOR.search(body) or [None, "ALL"])[1].upper()
    if cmd == "INSERT":
        return bool(_CHECK_TRUE.search(body))
    return bool(_USING_TRUE.search(body))


@pytest.mark.parametrize("migration_dir", MIGRATION_DIRS, ids=lambda d: str(d.relative_to(REPO)))
def test_no_surviving_allow_all_policy_for_api_roles(migration_dir: Path):
    offenders = []
    for (table, name), (source, body) in sorted(_surviving_policies(migration_dir).items()):
        if not _open_to_api_roles(body):
            continue
        cmd = (_FOR.search(body) or [None, "ALL"])[1].upper()
        if cmd == "SELECT" and (table, name) in ALLOWED_PUBLIC_READS:
            continue
        offenders.append(f"{table}.{name!r} ({cmd}) in {source}")
    assert not offenders, (
        "Allow-all RLS policies reachable with the public key survive the migration series "
        "(drop them — backend-only tables need no policy; a deliberate public SELECT goes in "
        "ALLOWED_PUBLIC_READS):\n  " + "\n  ".join(offenders)
    )


def test_allowed_public_reads_still_exist():
    """The allowlist is shrink-only: a stale entry must be removed, not kept as cover."""
    live = _surviving_policies(REPO / "infra" / "supabase" / "migrations")
    stale = ALLOWED_PUBLIC_READS - set(live)
    assert not stale, f"ALLOWED_PUBLIC_READS names policies no migration keeps alive: {sorted(stale)}"


def test_ratchet_sees_through_the_shapes_prod_used(tmp_path: Path):
    """Detection must cover the bare-role, TO-clause, INSERT-only and plpgsql-loop forms."""
    (tmp_path / "0001_create.sql").write_text(
        """
        CREATE POLICY "svc" ON public.charges USING (true) WITH CHECK (true);
        CREATE POLICY members_read ON public.orgs FOR SELECT USING (id IN (SELECT 1));
        CREATE POLICY "open insert" ON orgs FOR INSERT TO authenticated WITH CHECK (true);
        CREATE POLICY "service only" ON public.charges FOR ALL TO service_role USING (true) WITH CHECK (true);
        DO $$ DECLARE t text; BEGIN
          FOREACH t IN ARRAY ARRAY['cas_a', 'cas_b'] LOOP
            EXECUTE format('CREATE POLICY "Allow all for anon" ON public.%I FOR ALL TO anon USING (true) WITH CHECK (true)', t);
          END LOOP; END $$;
        CREATE TABLE gone (id int);
        CREATE POLICY "Allow all for authenticated users" ON public.gone USING (true) WITH CHECK (true);
        """
    )
    (tmp_path / "0002_fix.sql").write_text(
        """
        DROP POLICY IF EXISTS "Allow all for anon" ON public.cas_a;
        DROP TABLE IF EXISTS public.gone;
        """
    )
    open_ones = sorted(k for k, (_, body) in _surviving_policies(tmp_path).items() if _open_to_api_roles(body))
    assert open_ones == [("cas_b", "Allow all for anon"), ("charges", "svc"), ("orgs", "open insert")]

#!/usr/bin/env python3
"""Prepare a fresh NoClick database and object store, then exit.

Runs once before the backend starts (compose `depends_on: service_completed`).
It is idempotent, so restarting the stack is safe.

Ordering matters and is the reason this is a job rather than backend startup
code: the schema has foreign keys onto `auth.users`, and that table is created
by GoTrue's own migrations when the auth service first boots. Applying our
schema before then fails with a confusing missing-relation error, so we wait for
the table to appear.

Applied migrations are recorded in `supabase_migrations.schema_migrations`, the
same table the Supabase CLI uses, so an operator can move between `make local`
and Docker without reapplying anything.
"""

import asyncio
import os
import pathlib
import sys

import asyncpg

# GoTrue's first migration creates auth.uid() and auth.role() reading only the
# legacy per-claim settings. PostgREST stopped setting those in v12 — it sets
# one JSON `request.jwt.claims` — so with GoTrue's versions every RLS policy in
# the schema (54 auth.uid() calls) silently evaluates against NULL and the
# browser sees no rows. These read either shape, and are installed after GoTrue
# has migrated so its `create or replace` cannot fail on an object it does not
# own.
CLAIM_ACCESSORS = """
CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql STABLE AS $fn$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim', true), ''),
        nullif(current_setting('request.jwt.claims', true), '')
    )::jsonb
$fn$;
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $fn$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim.sub', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
    )::uuid
$fn$;
CREATE OR REPLACE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS $fn$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim.role', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
    )
$fn$;
CREATE OR REPLACE FUNCTION auth.email() RETURNS text LANGUAGE sql STABLE AS $fn$
    SELECT coalesce(
        nullif(current_setting('request.jwt.claim.email', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'email')
    )
$fn$;
GRANT EXECUTE ON FUNCTION auth.jwt(), auth.uid(), auth.role(), auth.email()
    TO anon, authenticated, service_role;
"""

MIGRATIONS = pathlib.Path(
    os.environ.get("NOCLICK_MIGRATIONS_DIR", "/app/infra/supabase/migrations")
)
DEADLINE_SECONDS = float(os.environ.get("NOCLICK_BOOTSTRAP_TIMEOUT", "300"))


def log(message: str) -> None:
    print(f"[bootstrap] {message}", flush=True)


async def _connect(dsn: str) -> asyncpg.Connection:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DEADLINE_SECONDS
    last: Exception | None = None
    while loop.time() < deadline:
        try:
            return await asyncpg.connect(dsn)
        except asyncpg.InvalidPasswordError:
            # Definitive, so retrying it for five minutes only delays the
            # message. The cause is almost always a data directory that belongs
            # to a different install: the volume name is derived from the
            # compose project, and the password from .env.
            raise SystemExit(
                "the database rejected the password in .env.\n"
                "  A previous install's data volume is likely still here. Either keep it\n"
                "  and restore that install's .env, or start fresh with "
                "`docker compose down -v`.\n"
                "  To run two instances on one host, give each its own "
                "COMPOSE_PROJECT_NAME."
            )
        except Exception as exc:  # server not accepting connections yet
            last = exc
            await asyncio.sleep(1.0)
    raise SystemExit(f"database never accepted a connection: {last}")


async def _wait_for_auth_users(conn: asyncpg.Connection) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DEADLINE_SECONDS
    while loop.time() < deadline:
        if await conn.fetchval("SELECT to_regclass('auth.users') IS NOT NULL"):
            return
        await asyncio.sleep(1.0)
    raise SystemExit(
        "auth.users never appeared — the auth service did not finish its "
        "migrations. Check `docker compose logs auth`."
    )


async def _apply_migrations(conn: asyncpg.Connection) -> None:
    await conn.execute("CREATE SCHEMA IF NOT EXISTS supabase_migrations")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supabase_migrations.schema_migrations (
            version text PRIMARY KEY,
            statements text[],
            name text
        )
        """
    )
    applied = {
        row["version"]
        for row in await conn.fetch("SELECT version FROM supabase_migrations.schema_migrations")
    }

    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        raise SystemExit(f"no migrations found in {MIGRATIONS}")

    for path in files:
        version, _, name = path.stem.partition("_")
        if version in applied:
            log(f"{path.name} already applied")
            continue
        log(f"applying {path.name}")
        # One transaction per migration: a failure leaves nothing half-applied
        # and the version unrecorded, so the next run retries it.
        async with conn.transaction():
            await conn.execute(path.read_text())
            await conn.execute(
                "INSERT INTO supabase_migrations.schema_migrations (version, name) VALUES ($1, $2)",
                version,
                name,
            )


def _ensure_buckets() -> None:
    endpoint = os.environ.get("OBJECT_STORAGE_ENDPOINT")
    if not endpoint:
        log("object storage not configured — file and media features stay disabled")
        return

    import time

    import boto3
    from botocore.exceptions import ClientError

    # Runtime call sites use these names as part of the storage contract. Do
    # not expose bootstrap-only bucket overrides that would provision one pair
    # while the application writes to another.
    buckets = ("workflow-resources", "workflow-cas")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["OBJECT_STORAGE_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["OBJECT_STORAGE_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
    )
    # The object store has no healthcheck to depend on — its image carries no
    # shell to probe with — so reachability is established by retrying here.
    deadline = time.monotonic() + DEADLINE_SECONDS
    for bucket in buckets:
        while True:
            try:
                client.head_bucket(Bucket=bucket)
                log(f"bucket {bucket} exists")
                break
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in (
                    "404", "NoSuchBucket", "NoSuchBucketException",
                ):
                    # Private by design. Browsers use short-lived presigned URLs;
                    # a public resource bucket would expose workflow files, while
                    # a public CAS bucket would expose execution output directly.
                    client.create_bucket(Bucket=bucket)
                    log(f"created private bucket {bucket}")
                    break
                raise
            except Exception as exc:
                if time.monotonic() > deadline:
                    raise SystemExit(f"object storage never became reachable: {exc}")
                time.sleep(1.0)


async def main() -> None:
    dsn = os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRES_POOLER_URL")
    if not dsn:
        raise SystemExit("POSTGRES_URL is required")

    conn = await _connect(dsn)
    try:
        await _wait_for_auth_users(conn)
        await conn.execute(CLAIM_ACCESSORS)
        log("claim accessors installed")
        await _apply_migrations(conn)
    finally:
        await conn.close()

    _ensure_buckets()
    log("ready")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit as exc:
        print(f"[bootstrap] {exc}", file=sys.stderr, flush=True)
        raise

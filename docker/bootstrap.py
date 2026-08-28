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

Three commands, because a one-click deploy has only a database to start from:

    prepare   the roles, schemas and extensions Supabase's API layer expects,
              on any stock Postgres — what compose gets from an initdb script
              and a managed database cannot run at all
    secrets   this instance's own secrets, as `export` lines. Environment wins;
              anything absent is generated once and kept in the database, which
              on a host that can neither generate a value nor mount a disk is
              the only place a key can survive a redeploy
    (default) the claim accessors, the schema migrations and the buckets
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import pathlib
import secrets as secretslib
import shlex
import sys
import time
import urllib.parse

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

# The roles, schemas and extensions Supabase's API layer expects to find. On
# compose this is an initdb script (docker/db/01-supabase-compat.sh); a managed
# database has no initdb hook, so the same shapes are made here — idempotently,
# because this runs on every boot rather than once on an empty data directory.
COMPAT_SQL = """
DO $do$
BEGIN
    -- PostgREST logs in as `authenticator` and assumes whichever of the other
    -- three the request's JWT names, so it must not inherit their rights by
    -- default — NOINHERIT is the boundary, not a style choice.
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticator') THEN
        CREATE ROLE authenticator LOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
        CREATE ROLE supabase_auth_admin LOGIN NOINHERIT CREATEROLE;
    END IF;
END
$do$;

-- A role password cannot be a query parameter, so it arrives as a session
-- setting and is quoted by the server rather than by string formatting here.
DO $do$
BEGIN
    EXECUTE format(
        'ALTER ROLE authenticator WITH PASSWORD %L',
        current_setting('noclick.role_password')
    );
    EXECUTE format(
        'ALTER ROLE supabase_auth_admin WITH PASSWORD %L',
        current_setting('noclick.role_password')
    );
END
$do$;

GRANT anon, authenticated, service_role TO authenticator;

-- GoTrue owns its schema and migrates it itself.
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION supabase_auth_admin;
ALTER ROLE supabase_auth_admin SET search_path TO auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;

-- Supabase keeps extensions out of `public`; the schema's
-- `extensions.gen_random_bytes` calls are written that way.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
GRANT USAGE ON SCHEMA extensions TO anon, authenticated, service_role;

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
"""

# Kept out of `public`, whose table list is a reviewed allowlist the release
# pins, and readable by nobody the API layer can reach: the schema is never
# exposed through PostgREST, and no role but the migration user is granted it.
SECRETS_SCHEMA = """
CREATE SCHEMA IF NOT EXISTS noclick_instance;
REVOKE ALL ON SCHEMA noclick_instance FROM PUBLIC;
CREATE TABLE IF NOT EXISTS noclick_instance.secrets (
    name text PRIMARY KEY,
    value text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
"""

# Every secret the instance needs and can mint for itself. The credential key is
# a Fernet key because that is what encrypts stored credentials; the rest are
# opaque random strings.
SECRET_GENERATORS = {
    "JWT_SECRET": lambda: secretslib.token_hex(32),
    "CREDENTIALS_ENCRYPTION_KEY": lambda: base64.urlsafe_b64encode(
        secretslib.token_bytes(32)
    ).decode(),
    "WORKFLOW_JWT_SECRET": lambda: secretslib.token_hex(32),
    "CRON_SCHEDULER_SECRET": lambda: secretslib.token_hex(32),
    "SESSION_SECRET": lambda: secretslib.token_hex(32),
    "EMAIL_RELAY_SECRET": lambda: secretslib.token_hex(32),
    # Not an application secret: the login password for the two roles GoTrue
    # and PostgREST connect as, which nothing outside this container ever sees.
    "SUPABASE_DB_ROLE_PASSWORD": lambda: secretslib.token_hex(24),
}


def _role_dsn(dsn: str, user: str, password: str) -> str:
    """The same database, reached as a different role. Query parameters carry
    `sslmode` on every managed provider, so they are preserved verbatim."""
    parts = urllib.parse.urlsplit(dsn)
    netloc = (
        f"{urllib.parse.quote(user, safe='')}:{urllib.parse.quote(password, safe='')}"
        f"@{parts.hostname or ''}"
    )
    if parts.port:
        netloc += f":{parts.port}"
    return urllib.parse.urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )


def _sign_supabase_key(role: str, jwt_secret: str) -> str:
    """An anon or service-role key: an HS256 JWT naming the Postgres role, which
    is all those keys have ever been. Derived from the instance's JWT secret on
    every boot rather than stored, so there is one secret to keep, not three."""

    def segment(payload: dict) -> bytes:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    issued = int(time.time())
    signing_input = segment({"alg": "HS256", "typ": "JWT"}) + b"." + segment(
        {
            "role": role,
            "iss": "supabase",
            "iat": issued,
            "exp": issued + 10 * 365 * 24 * 3600,
        }
    )
    signature = base64.urlsafe_b64encode(
        hmac.new(jwt_secret.encode(), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    return (signing_input + b"." + signature).decode()


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


async def _provision_secrets(conn: asyncpg.Connection) -> dict:
    """This instance's secrets: the environment's where it has them, and
    generated-once-and-kept where it does not.

    Keeping a generated key beside the data it protects is weaker than holding
    it in the platform's own secret store, and where a platform can generate one
    its deploy config does — this is what makes an instance possible at all on a
    host that can neither generate a value nor mount a disk to keep one on.
    """
    await conn.execute(SECRETS_SCHEMA)
    resolved: dict[str, str] = {}
    for name, generate in SECRET_GENERATORS.items():
        supplied = os.environ.get(name)
        if supplied:
            resolved[name] = supplied
            continue
        # Insert-then-read rather than read-then-insert: two containers booting
        # at once must agree on one value, and the primary key decides which.
        await conn.execute(
            "INSERT INTO noclick_instance.secrets (name, value) VALUES ($1, $2) "
            "ON CONFLICT (name) DO NOTHING",
            name,
            generate(),
        )
        resolved[name] = await conn.fetchval(
            "SELECT value FROM noclick_instance.secrets WHERE name = $1", name
        )
    return resolved


async def prepare(conn: asyncpg.Connection, role_password: str) -> None:
    await conn.execute(
        "SELECT set_config('noclick.role_password', $1, false)", role_password
    )
    await conn.execute(COMPAT_SQL)
    log("supabase-compatible roles, schemas and extensions ready")

    # Reading the service key is how the application reaches rows RLS scopes to
    # a user. Only a superuser can grant the exemption, which a managed database
    # does not hand out — so this is reported, never assumed.
    if await conn.fetchval("SELECT usesuper FROM pg_user WHERE usename = current_user"):
        await conn.execute("ALTER ROLE service_role WITH BYPASSRLS")
    elif not await conn.fetchval(
        "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'service_role'"
    ):
        log(
            "WARNING: this database user cannot grant BYPASSRLS, so service-role "
            "reads stay subject to row-level security. Sign-in and every workflow "
            "are unaffected; a few admin-level reads through PostgREST will "
            "return nothing."
        )


async def command_secrets() -> None:
    """Print `export` lines for everything the entrypoint needs to start the
    embedded auth stack. Values are shell-quoted; nothing is echoed to a log."""
    dsn = _require_dsn()
    conn = await _connect(dsn)
    try:
        secrets = await _provision_secrets(conn)
    finally:
        await conn.close()

    role_password = secrets["SUPABASE_DB_ROLE_PASSWORD"]
    jwt_secret = secrets["JWT_SECRET"]
    emit = dict(secrets)
    emit["SUPABASE_JWT_SECRET"] = jwt_secret
    emit["SUPABASE_ANON_KEY"] = _sign_supabase_key("anon", jwt_secret)
    emit["SUPABASE_SECRET_KEY"] = _sign_supabase_key("service_role", jwt_secret)
    emit["GOTRUE_DB_DATABASE_URL"] = _role_dsn(dsn, "supabase_auth_admin", role_password)
    emit["PGRST_DB_URI"] = _role_dsn(dsn, "authenticator", role_password)

    for name, value in emit.items():
        print(f"export {name}={shlex.quote(value)}")


def _require_dsn() -> str:
    dsn = os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRES_POOLER_URL")
    if not dsn:
        raise SystemExit("POSTGRES_URL is required")
    return dsn


async def command_prepare() -> None:
    conn = await _connect(_require_dsn())
    try:
        secrets = await _provision_secrets(conn)
        await prepare(conn, secrets["SUPABASE_DB_ROLE_PASSWORD"])
    finally:
        await conn.close()


async def main() -> None:
    conn = await _connect(_require_dsn())
    try:
        await _wait_for_auth_users(conn)
        await conn.execute(CLAIM_ACCESSORS)
        log("claim accessors installed")
        await _apply_migrations(conn)
    finally:
        await conn.close()

    _ensure_buckets()
    log("ready")


COMMANDS = {"prepare": command_prepare, "secrets": command_secrets}

if __name__ == "__main__":
    argument = sys.argv[1] if len(sys.argv) > 1 else None
    if argument is not None and argument not in COMMANDS:
        raise SystemExit(f"unknown command {argument!r}: expected one of {sorted(COMMANDS)}")
    try:
        asyncio.run(COMMANDS[argument]() if argument else main())
    except SystemExit as exc:
        print(f"[bootstrap] {exc}", file=sys.stderr, flush=True)
        raise

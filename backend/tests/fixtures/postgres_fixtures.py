"""
Pytest fixtures for PostgreSQL-based database testing using testcontainers.

Provides fixtures for creating PostgreSQL containers with migrations applied.
"""

import sys
import pytest
import pytest_asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator
from testcontainers.postgres import PostgresContainer

from backend.tests.utils import find_project_root

# IMPORTANT: Restore real asyncpg if it was mocked by other tests
# (tests/mocks/mock_asyncpg.py swaps sys.modules); we need the real one for
# testcontainers.
def restore_real_asyncpg() -> None:
    """Put the ORIGINAL asyncpg module objects back in sys.modules.

    mock_asyncpg stashes the real module it imported before installing the
    mock — restore THAT object. Deleting + re-importing instead would mint a
    second copy of every asyncpg exception class, and `except` matches on
    class identity: modules bound to the first copy then silently fail to
    catch exceptions raised from the second (order-dependent suite flake).
    """
    from unittest.mock import MagicMock

    mocked = sys.modules.get('asyncpg')
    if not isinstance(mocked, MagicMock):
        return
    real = getattr(mocked, '__real_asyncpg__', None)
    if real is None:
        raise RuntimeError(
            "asyncpg is mocked but carries no __real_asyncpg__ stash — "
            "was it mocked by something other than tests/mocks/mock_asyncpg.py?"
        )
    sys.modules['asyncpg'] = real
    sys.modules['asyncpg.exceptions'] = real.exceptions


restore_real_asyncpg()

# Now import real asyncpg
import asyncpg

# Export exception classes for tests to use (ensures same module instance)
from asyncpg.exceptions import UniqueViolationError, ForeignKeyViolationError

# Explicitly declare exports
__all__ = ['postgres_container', 'postgres_db', 'UniqueViolationError', 'ForeignKeyViolationError']

logger = logging.getLogger(__name__)


def get_migrations_dir() -> Path:
    """Get the path to the migrations directory."""
    project_root = find_project_root()
    return project_root / "infra" / "supabase" / "migrations"


def get_seed_file() -> Path:
    """Get the path to the seed.sql file."""
    project_root = find_project_root()
    return project_root / "infra" / "supabase" / "seed.sql"


async def setup_supabase_basics(conn: asyncpg.Connection) -> None:
    """
    Set up basic Supabase-like environment (auth schema, tables, etc.).

    Args:
        conn: asyncpg connection
    """
    # Create extensions schema with pgcrypto (Supabase puts extensions here)
    # Set search_path on both current session and database default for future connections
    await conn.execute("CREATE SCHEMA IF NOT EXISTS extensions")
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA extensions")
    await conn.execute("SET search_path TO public, extensions")
    await conn.execute("ALTER DATABASE test SET search_path TO public, extensions")

    # Create auth schema
    await conn.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # Create full Supabase auth.users table to support seed.sql
    # Based on Supabase auth schema v20240101
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auth.users (
            instance_id UUID,
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            aud VARCHAR(255),
            role VARCHAR(255),
            email VARCHAR(255) UNIQUE,
            encrypted_password VARCHAR(255),
            email_confirmed_at TIMESTAMPTZ,
            invited_at TIMESTAMPTZ,
            confirmation_token VARCHAR(255),
            confirmation_sent_at TIMESTAMPTZ,
            recovery_token VARCHAR(255),
            recovery_sent_at TIMESTAMPTZ,
            email_change_token_new VARCHAR(255),
            email_change VARCHAR(255),
            email_change_sent_at TIMESTAMPTZ,
            last_sign_in_at TIMESTAMPTZ,
            raw_app_meta_data JSONB,
            raw_user_meta_data JSONB,
            is_super_admin BOOLEAN,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            phone VARCHAR(255),
            phone_confirmed_at TIMESTAMPTZ,
            phone_change VARCHAR(255),
            phone_change_token VARCHAR(255),
            phone_change_sent_at TIMESTAMPTZ,
            email_change_token_current VARCHAR(255),
            email_change_confirm_status SMALLINT,
            banned_until TIMESTAMPTZ,
            reauthentication_token VARCHAR(255),
            reauthentication_sent_at TIMESTAMPTZ,
            is_sso_user BOOLEAN DEFAULT FALSE,
            deleted_at TIMESTAMPTZ,
            is_anonymous BOOLEAN DEFAULT FALSE
        )
    """)

    # Create auth.identities table for OAuth providers
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auth.identities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider_id VARCHAR(255) NOT NULL,
            user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            identity_data JSONB NOT NULL,
            provider VARCHAR(255) NOT NULL,
            last_sign_in_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Create auth.mfa_amr_claims table for MFA
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auth.mfa_amr_claims (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            authentication_method VARCHAR(255) NOT NULL
        )
    """)

    # Create auth.refresh_tokens sequence (needed by seed.sql)
    await conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS auth.refresh_tokens_id_seq
    """)

    # Create a mock auth.uid() function for RLS policies
    # This will return NULL in tests since we're not using real auth
    await conn.execute("""
        CREATE OR REPLACE FUNCTION auth.uid()
        RETURNS UUID AS $$
        BEGIN
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    # Create service_role role if it doesn't exist
    try:
        await conn.execute("CREATE ROLE service_role")
    except asyncpg.exceptions.DuplicateObjectError:
        pass  # Role already exists

    # Create anon role if it doesn't exist
    try:
        await conn.execute("CREATE ROLE anon")
    except asyncpg.exceptions.DuplicateObjectError:
        pass  # Role already exists

    # Create authenticated role if it doesn't exist
    try:
        await conn.execute("CREATE ROLE authenticated")
    except asyncpg.exceptions.DuplicateObjectError:
        pass  # Role already exists

    # Create supabase_auth_admin role if it doesn't exist
    try:
        await conn.execute("CREATE ROLE supabase_auth_admin")
    except asyncpg.exceptions.DuplicateObjectError:
        pass  # Role already exists

    logger.info("Set up basic Supabase environment")


async def apply_migrations(conn: asyncpg.Connection) -> int:
    """
    Apply all migrations from infra/supabase/migrations to the database.

    Args:
        conn: asyncpg connection

    Returns:
        Number of migrations applied
    """
    migrations_dir = get_migrations_dir()
    if not migrations_dir.exists():
        logger.error(f"Migrations directory not found: {migrations_dir}")
        return 0

    migration_files = sorted(migrations_dir.glob("*.sql"))
    count = 0

    for filepath in migration_files:
        logger.info(f"Applying migration: {filepath.name}")

        # Read migration content
        sql = filepath.read_text()

        try:
            # Execute the migration SQL
            await conn.execute(sql)
            count += 1
            logger.info(f"Successfully applied migration: {filepath.name}")
        except Exception as e:
            logger.error(f"Failed to apply migration {filepath.name}: {e}")
            raise

    return count


async def apply_seed_data(conn: asyncpg.Connection) -> None:
    """
    Apply seed data from infra/supabase/seed.sql to the database.

    Args:
        conn: asyncpg connection
    """
    seed_file = get_seed_file()
    if not seed_file.exists():
        logger.warning(f"Seed file not found: {seed_file}")
        return

    logger.info(f"Applying seed data from: {seed_file.name}")

    # Read seed content
    sql = seed_file.read_text()

    try:
        # Execute the seed SQL
        await conn.execute(sql)
        logger.info("Successfully applied seed data")
    except Exception as e:
        logger.warning(f"Failed to apply seed data (non-fatal): {e}")
        # Don't raise - seed data is optional and may conflict with test data


@pytest.fixture(scope="session")
def postgres_container():
    """
    Session-scoped fixture that provides a PostgreSQL container.

    The container is started once per test session and reused across all tests.
    """
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        logger.info(f"Started PostgreSQL container: {postgres.get_connection_url()}")
        # Mark container as not initialized (use container object for state)
        postgres._test_db_initialized = False
        yield postgres


async def _initialize_database_once(container):
    """Helper function to initialize the database once."""
    # Use container object for state instead of global variable
    if hasattr(container, '_test_db_initialized') and container._test_db_initialized:
        return

    # Create a connection to set up the database
    conn = await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=container.get_exposed_port(5432),
        user=container.username,
        password=container.password,
        database=container.dbname,
    )

    try:
        # Set up basic Supabase environment
        await setup_supabase_basics(conn)

        # Apply migrations
        migrations_count = await apply_migrations(conn)
        logger.info(f"Applied {migrations_count} migrations")

        # Apply seed data
        await apply_seed_data(conn)

        # Insert test user into auth.users
        # Using a fixed UUID for consistent test data
        await conn.execute("""
            INSERT INTO auth.users (id, email)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
        """, "00000000-0000-0000-0000-000000000001", "test@example.com")

        logger.info("PostgreSQL test database initialized with migrations and seed data")
        # Mark as initialized on container object (not global variable)
        container._test_db_initialized = True

    finally:
        await conn.close()


async def reset_database_data(container) -> None:
    """Restore the shared test container to its migration-only baseline.

    The public CI suite deliberately keeps every Postgres-backed module on one
    xdist worker so a single container can serve the run. Historically each
    test module imported ``postgres_container`` directly, which accidentally
    created a separate session fixture (and therefore a fresh database) per
    module. Reset rows at module boundaries to preserve that isolation without
    repeatedly starting and stopping Docker containers.
    """
    await _initialize_database_once(container)

    conn = await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=container.get_exposed_port(5432),
        user=container.username,
        password=container.password,
        database=container.dbname,
    )

    try:
        # Workflow database tests materialize arbitrary tables in this schema.
        # Dropping the schema clears both those tables and their owned sequences.
        await conn.execute("DROP SCHEMA IF EXISTS user_tables CASCADE")
        await conn.execute("CREATE SCHEMA user_tables")

        rows = await conn.fetch(
            """
            SELECT n.nspname AS schema_name, c.relname AS table_name
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname <> 'information_schema'
              AND n.nspname NOT LIKE 'pg_%'
              AND n.nspname <> 'user_tables'
            ORDER BY n.nspname, c.relname
            """
        )
        if rows:
            def quote_identifier(value: str) -> str:
                return '"' + value.replace('"', '""') + '"'

            tables = ", ".join(
                f"{quote_identifier(row['schema_name'])}."
                f"{quote_identifier(row['table_name'])}"
                for row in rows
            )
            await conn.execute(
                f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"
            )

        await apply_seed_data(conn)
        await conn.execute(
            """
            INSERT INTO auth.users (id, email)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
            """,
            "00000000-0000-0000-0000-000000000001",
            "test@example.com",
        )
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def postgres_db(postgres_container) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Fixture that provides a PostgreSQL database connection with migrations applied.

    Each test runs in a transaction that is rolled back after the test completes,
    ensuring test isolation.

    Usage:
        async def test_something(postgres_db):
            result = await postgres_db.fetch("SELECT * FROM user_tables_metadata")
    """
    # Initialize database once (idempotent)
    await _initialize_database_once(postgres_container)

    # Extract connection parameters from container
    conn = await asyncpg.connect(
        host=postgres_container.get_container_host_ip(),
        port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username,
        password=postgres_container.password,
        database=postgres_container.dbname,
    )

    # Register asyncpg type codecs (JSONB auto-conversion, etc.)
    from utils.database_pool import setup_asyncpg_codecs
    await setup_asyncpg_codecs(conn)

    # Start a transaction for test isolation
    # Handle both sync and async transaction APIs for asyncpg compatibility
    import inspect
    transaction_obj = conn.transaction()
    if inspect.iscoroutine(transaction_obj):
        transaction = await transaction_obj
    else:
        transaction = transaction_obj

    await transaction.start()

    try:
        yield conn
    finally:
        # Always rollback to ensure test isolation
        # (Transaction might be in failed state if test raised an exception)
        try:
            await transaction.rollback()
        except Exception as e:
            # Transaction might already be aborted
            logger.warning(f"Error during rollback (may already be aborted): {e}")

        await conn.close()
        logger.info("Rolled back transaction and closed connection")

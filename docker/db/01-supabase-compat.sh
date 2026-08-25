#!/bin/sh
# The API layer that ships with this stack — GoTrue for sign-in, PostgREST for
# the two tables the browser reads directly — is Supabase's, and it expects a
# handful of roles, a schema and four claim accessors to already exist. Supabase
# gets them from a 1.5 GB customised Postgres image; this is the part of it that
# NoClick actually depends on, on top of stock Postgres.
#
# The auth.uid() family is deliberately NOT here — GoTrue's own first migration
# creates those functions and would fail on ones it does not own. bootstrap.py
# installs the working versions afterwards.
#
# Runs once, on an empty data directory, as the superuser.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    -- API roles. PostgREST logs in as \`authenticator\` and assumes whichever of
    -- the other three the request's JWT names, so it must not inherit their
    -- rights by default — NOINHERIT is the boundary, not a style choice.
    CREATE ROLE anon NOLOGIN NOINHERIT;
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
    CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
    CREATE ROLE authenticator LOGIN NOINHERIT PASSWORD '${POSTGRES_PASSWORD}';
    GRANT anon, authenticated, service_role TO authenticator;

    -- GoTrue owns its schema and migrates it itself.
    CREATE ROLE supabase_auth_admin LOGIN NOINHERIT CREATEROLE PASSWORD '${POSTGRES_PASSWORD}';
    CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION supabase_auth_admin;
    ALTER ROLE supabase_auth_admin SET search_path TO auth;
    GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;

    -- Supabase keeps extensions out of \`public\`; the schema's
    -- \`extensions.gen_random_bytes\` calls are written that way.
    CREATE SCHEMA IF NOT EXISTS extensions;
    CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
    GRANT USAGE ON SCHEMA extensions TO anon, authenticated, service_role;
    ALTER DATABASE "${POSTGRES_DB}" SET search_path TO "\$user", public, extensions;

    GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
SQL

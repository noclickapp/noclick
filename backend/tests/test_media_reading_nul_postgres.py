"""A document whose text layer carries NUL characters, read against real
Postgres: the reading is kept on the file without them and the next turn
reuses it. Postgres jsonb refuses ``\\u0000``, so keeping such a reading
failed the agent turn that read it."""

import uuid

import pytest

from nodes.core import media_digest as md
from repositories.resources import ResourceReadings
from tests.mocks.pdf_fixtures import text_pdf

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pool(postgres_db, postgres_container):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=2, init=setup_asyncpg_codecs,
    )
    try:
        yield pool
    finally:
        await pool.close()


async def test_a_pdf_with_nul_characters_is_read_and_kept(pool, monkeypatch):
    owner = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:8]}@example.com"))
    resource_id = str(await pool.fetchval(
        "INSERT INTO workflow_resources (owner_id, resource_type, name, mime_type) "
        "VALUES ($1::uuid, 'document', 'statement.pdf', 'application/pdf') RETURNING id", owner))

    async def fetch(ref, ctx, max_bytes):
        return text_pdf("Total\\000due")  # a PDF string's octal escape: a NUL in the text layer

    monkeypatch.setattr(md, "_fetch", fetch)
    ctx = md.DigestContext(owner_id=owner, readings=ResourceReadings(owner, pool))

    def ref():
        return md.MediaRef(kind="document", mime_type="application/pdf", resource_id=resource_id,
                           filename="statement.pdf", record={})

    (first,) = await md.digest_media([ref()], ctx)
    assert first.error is None and first.text == "Totaldue" and not first.kept
    metadata = await pool.fetchval("SELECT metadata FROM workflow_resources WHERE id = $1::uuid", resource_id)
    assert metadata["extracted_text"] == "Totaldue" and "reading_until" not in metadata

    (again,) = await md.digest_media([ref()], ctx)
    assert again.text == "Totaldue" and again.kept

"""cas_manifests keeps one index leading with workflow_id, which the cascade from workflows and every lookup by
workflow use (idx_cas_manifests_node_recency); the plain one on workflow_id alone was dropped as its duplicate."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_the_cascade_from_workflows_keeps_an_index_and_no_duplicate(postgres_db):
    leading = await postgres_db.fetch(
        """SELECT c.relname, i.indnatts FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
            WHERE i.indrelid = 'public.cas_manifests'::regclass
              AND (SELECT attname FROM pg_attribute WHERE attrelid = i.indrelid AND attnum = i.indkey[0]) = 'workflow_id'
              AND i.indpred IS NULL""")
    assert {r["relname"] for r in leading} == {"idx_cas_manifests_node_recency"}

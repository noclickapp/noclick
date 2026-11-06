"""Each account's own node output shapes (``account_node_output_schemas``), kept beside the pooled table by
``utils.node_schema_tracker``, for what a person or a client outside NoClick reads."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


async def record(pool, *, workflow_id: str, node_type: str, node_operation: str, schema: Any, schema_hash: str,
                 delivered: bool) -> None:
    """One more of this shape for the account that owns the workflow; a workflow no row holds has no account."""
    await pool.execute(
        """INSERT INTO account_node_output_schemas
               (user_id, schema_hash, node_type, node_operation, output_schema, delivered)
           SELECT owner_id, $2::text, $3::text, $4::text, $5::jsonb, $6::boolean FROM workflows WHERE id = $1::uuid
           ON CONFLICT (user_id, schema_hash) DO UPDATE SET
               occurrence_count = account_node_output_schemas.occurrence_count + 1,
               last_seen_at = now(),
               delivered = account_node_output_schemas.delivered OR EXCLUDED.delivered""",
        workflow_id, schema_hash, node_type, node_operation, schema, delivered)


async def most_seen(pool, user_id: str, node_type: str, node_operation: str) -> Optional[Dict[str, Any]]:
    """The shape seen most of this (type, operation) by the account or anyone in a workspace with it, whose
    workflows it can open (each run records under its workflow's owner), with the references curated for it."""
    row = await pool.fetchrow(
        """WITH people AS (
               SELECT $1::uuid AS user_id
               UNION
               SELECT theirs.user_id FROM organization_members mine
               JOIN organization_members theirs ON theirs.organization_id = mine.organization_id
               WHERE mine.user_id = $1::uuid),
           seen AS (
               SELECT own.schema_hash, (array_agg(own.output_schema))[1] AS output_schema,
                      sum(own.occurrence_count) AS n
               FROM account_node_output_schemas own JOIN people USING (user_id)
               WHERE own.node_type = $2 AND own.node_operation = $3
               GROUP BY own.schema_hash ORDER BY n DESC, own.schema_hash LIMIT 1)
           SELECT seen.output_schema, pooled.suggested_refs FROM seen
           LEFT JOIN workflow_node_output_schemas pooled ON pooled.schema_hash = seen.schema_hash""",
        user_id, node_type, node_operation)
    return dict(row) if row else None


async def delivered_shapes(pool, user_id: str, node_type: str, operations: List[str], *, limit: int) -> List[Any]:
    """(node_operation, output_schema) of what deliveries carried to the account, by operation, the ``limit`` seen
    most often of each, those first."""
    return await pool.fetch(
        """SELECT node_operation, output_schema FROM (
               SELECT node_operation, output_schema,
                      row_number() OVER (PARTITION BY node_operation
                                         ORDER BY occurrence_count DESC, schema_hash) AS n
               FROM account_node_output_schemas
               WHERE user_id = $1::uuid AND node_type = $2 AND node_operation = ANY($3::text[]) AND delivered) s
           WHERE n <= $4 ORDER BY node_operation, n""",
        user_id, node_type, list(operations), limit)

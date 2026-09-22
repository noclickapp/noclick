"""Account-owned memory storage with separate retrieval headers and bodies.
Versioned writes protect user edits, and deletion erases content while retaining
a name tombstone so stale agents cannot recreate the same memory.
"""

from typing import Optional

from utils.coordinator_memory import CoordinatorMemoryWrite


HEADER_COLUMNS = "id, name, description, memory_type, origin_conversation_id, version, created_at, updated_at"


class MemoryConflict(ValueError):
    pass


def memory_view(row):
    result = dict(row)
    result["id"] = str(result["id"])
    for key in ("created_at", "updated_at"):
        result[key] = result[key].isoformat()
    return result


class CoordinatorMemoryRepo:
    def __init__(self, pool):
        self.pool = pool

    async def list_headers(self, user_id: str, *, query: str = "", limit: int = 40, offset: int = 0):
        query = query.strip()
        if len(query) > 300 or not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise ValueError("Invalid memory search or page.")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT {HEADER_COLUMNS} FROM coordinator_memories
                    WHERE user_id = $1::uuid AND deleted_at IS NULL
                    AND ($2 = '' OR search_document @@ websearch_to_tsquery('simple', $2)
                         OR strpos(lower(name || ' ' || description), lower($2)) > 0)
                    ORDER BY CASE WHEN $2 <> '' THEN
                        ts_rank(search_document, websearch_to_tsquery('simple', $2)) ELSE 0 END DESC,
                        (memory_type IN ('user', 'feedback')) DESC, updated_at DESC, id
                    LIMIT $3 OFFSET $4""",
                user_id, query, limit + 1, offset,
            )
        return {"memories": [memory_view(r) for r in rows[:limit]], "has_more": len(rows) > limit}

    async def get(self, user_id: str, memory_id: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {HEADER_COLUMNS}, content FROM coordinator_memories "
                "WHERE user_id = $1::uuid AND id = $2::uuid AND deleted_at IS NULL", user_id, memory_id,
            )
        if row is None:
            raise ValueError("Memory not found.")
        return memory_view(row)

    async def save(self, user_id: str, memory: CoordinatorMemoryWrite, *, origin_conversation_id: Optional[str] = None, conn=None):
        if conn is None:
            async with self.pool.acquire() as connection:
                return await self.save(user_id, memory, origin_conversation_id=origin_conversation_id, conn=connection)
        async with conn.transaction():
            # Serialize creates/counts and duplicate-name checks across containers.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"coordinator-memory:{user_id}")
            duplicate = await conn.fetchrow(
                "SELECT id, deleted_at FROM coordinator_memories WHERE user_id = $1::uuid AND name = $2",
                user_id, memory.name,
            )
            if duplicate and duplicate["id"] != memory.memory_id:
                if duplicate["deleted_at"]:
                    raise MemoryConflict("This memory was forgotten. Do not recreate it from old conversations.")
                raise MemoryConflict("A memory with this name already exists. Read it before updating it.")
            if memory.memory_id:
                row = await conn.fetchrow(
                    f"""UPDATE coordinator_memories SET name=$3, description=$4, memory_type=$5, content=$6,
                        version=version+1, updated_at=clock_timestamp()
                        WHERE user_id=$1::uuid AND id=$2::uuid AND version=$7 AND deleted_at IS NULL
                        RETURNING {HEADER_COLUMNS}, content""",
                    user_id, memory.memory_id, memory.name, memory.description, memory.memory_type,
                    memory.content, memory.expected_version,
                )
                if row is None:
                    raise MemoryConflict("Memory changed or was deleted. Reload it before making another edit.")
            else:
                count = await conn.fetchval(
                    "SELECT count(*) FROM coordinator_memories WHERE user_id=$1::uuid AND deleted_at IS NULL", user_id,
                )
                if count >= 500:
                    raise ValueError("Memory is full (500 entries). Merge or delete existing entries first.")
                row = await conn.fetchrow(
                    f"""INSERT INTO coordinator_memories
                        (user_id, name, description, memory_type, content, origin_conversation_id)
                        VALUES ($1::uuid, $2, $3, $4, $5, $6) RETURNING {HEADER_COLUMNS}, content""",
                    user_id, memory.name, memory.description, memory.memory_type, memory.content, origin_conversation_id,
                )
        return memory_view(row)

    async def delete(self, user_id: str, memory_id: str, expected_version: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE coordinator_memories SET deleted_at=clock_timestamp(), updated_at=clock_timestamp(),
                   description='', content='', origin_conversation_id=NULL, version=version+1
                   WHERE user_id=$1::uuid AND id=$2::uuid AND version=$3 AND deleted_at IS NULL RETURNING id""",
                user_id, memory_id, expected_version,
            )
        if row is None:
            raise MemoryConflict("Memory changed or was deleted. Reload it before deleting.")
        return {"deleted": True}

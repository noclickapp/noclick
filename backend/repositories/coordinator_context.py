"""Checkpoint bookkeeping only. All retained semantic context lives in a visible memory."""

from coder.openai_agent.compaction import fingerprint  # noqa: F401 (callers read it here too)
from repositories.coordinator_memories import CoordinatorMemoryRepo, MemoryConflict


class CoordinatorContextRepo:
    def __init__(self, pool, user_id):
        self.pool, self.user_id = pool, user_id
        self.conversation_id = f"coordinator:{user_id}"

    async def load(self):
        metadata = await self.pool.fetchval(
            "SELECT metadata FROM conversations WHERE conversation_id=$1 AND user_id=$2::uuid",
            self.conversation_id, self.user_id,
        ) or {}
        return metadata.get("coordinator_context") or {}, metadata.get("sdk_history") or []

    async def commit(self, *, previous, prefix, memory, epoch):
        # A turn's call, or the fold after it that holds no turn lock: the epoch, pointer and history prefix are
        # compared here and the memory's version on save, so whatever moved first wins; both change atomically.
        async with self.pool.acquire() as conn, conn.transaction():
            metadata = await conn.fetchval(
                "SELECT metadata FROM conversations WHERE conversation_id=$1 AND user_id=$2::uuid FOR UPDATE",
                self.conversation_id, self.user_id,
            ) or {}
            history = metadata.get("sdk_history") or []
            if ((metadata.get("coordinator_epoch") or "") != epoch
                    or (metadata.get("coordinator_context") or {}) != previous
                    or len(history) < len(prefix) or fingerprint(history[:len(prefix)]) != fingerprint(prefix)):
                raise MemoryConflict("Conversation changed while compacting; history was preserved.")
            saved = await CoordinatorMemoryRepo(self.pool).save(
                self.user_id, memory, origin_conversation_id=self.conversation_id, conn=conn,
            )
            checkpoint = {"memory_id": saved["id"], "covered": len(prefix), "fingerprint": fingerprint(prefix), "version": 1}
            await conn.execute(
                "UPDATE conversations SET metadata=jsonb_set(COALESCE(metadata,'{}'::jsonb),"
                "'{coordinator_context}', $3::jsonb) WHERE conversation_id=$1 AND user_id=$2::uuid",
                self.conversation_id, self.user_id, checkpoint,
            )
            return checkpoint, saved

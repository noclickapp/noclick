"""The coordinator's context checkpoints: the engine's ``Compactor``
(``coder.openai_agent.compaction``) over the coordinator's conversation and
its memory library, where the checkpoint is a visible, editable memory."""

import uuid

from coder.openai_agent.compaction import (  # noqa: F401 (re-exported for callers and tests)
    MAX_SUMMARIES, TARGET_CHARACTERS, Budget, CheckpointConflict, Compactor, ContextBudgetError, Summary, image_inputs,
    parse_summary, safe_boundaries, summarize, token_count,
)
from repositories.coordinator_context import CoordinatorContextRepo
from repositories.coordinator_memories import CoordinatorMemoryRepo, MemoryConflict
from utils.coordinator_memory import CoordinatorMemoryWrite


class CoordinatorCheckpoints:
    """The coordinator conversation's checkpoint: a ``coordinator-context-*``
    memory, its pointer in the conversation's metadata, fenced by the reset epoch."""

    def __init__(self, pool, user_id, *, epoch):
        self.repo = CoordinatorContextRepo(pool, user_id)
        self.memories = CoordinatorMemoryRepo(pool)
        self.user_id, self.epoch = user_id, epoch

    async def load(self):
        return await self.repo.load()

    async def read(self, checkpoint):
        if not checkpoint.get("memory_id"):
            return None
        try:
            return await self.memories.get(self.user_id, checkpoint["memory_id"])
        except ValueError:
            return None  # forgotten

    async def commit(self, *, previous, prefix, summary, current):
        write = CoordinatorMemoryWrite(
            name=current["name"] if current else f"coordinator-context-{uuid.uuid4().hex[:12]}",
            description=summary.description, memory_type="project", content=summary.content,
            memory_id=current["id"] if current else None, expected_version=current["version"] if current else None,
        )
        try:
            return await self.repo.commit(previous=previous, prefix=prefix, memory=write, epoch=self.epoch)
        except MemoryConflict as conflict:
            raise CheckpointConflict(str(conflict)) from conflict


class CoordinatorCompactor(Compactor):
    def __init__(self, pool, user_id, *, epoch, model, user_email=None, organization_id=None, budget=None):
        store = CoordinatorCheckpoints(pool, user_id, epoch=epoch)
        super().__init__(store, model=model, user_id=user_id, user_email=user_email,
                         organization_id=organization_id, budget=budget)
        self.repo, self.memories = store.repo, store.memories

    # This module's names, looked up when called, so a test that replaces them here is heard.
    async def _summarize(self, previous, items):
        return await summarize(previous, items, model=self.model, user_id=self.user_id, user_email=self.user_email,
                               organization_id=self.organization_id)

    def _count(self, value):
        return token_count(value, self.model)

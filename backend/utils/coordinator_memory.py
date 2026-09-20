"""Shared contracts for the coordinator's durable memories.
Retrieval descriptions are authored separately from the Markdown body; neither
the prompt catalog nor list responses derive an excerpt from that body.
"""

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


MemoryType = Literal["user", "feedback", "project", "reference"]


class CoordinatorMemoryWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str = Field(min_length=1, max_length=600)
    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=16000)
    memory_id: Optional[UUID] = None
    expected_version: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def version_matches_operation(self):
        if (self.memory_id is None) != (self.expected_version is None):
            raise ValueError("Updates require both memory_id and expected_version; creates require neither.")
        return self

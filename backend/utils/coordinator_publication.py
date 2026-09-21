"""The explicit publication requested alongside a coordinator build."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def is_coordinator_build(user_id, conversation_id):
    return bool(user_id and conversation_id and conversation_id.startswith(f"coordinator-builder:{user_id}:"))


class PublicationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subdomain: str = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    node_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    send_to_phone: bool = False

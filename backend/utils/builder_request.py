"""The requested outcome of a builder run, independent of its caller."""

from pydantic import BaseModel, ConfigDict, Field

BUILDER_REQUEST_PREFIX = "builder-request:"


def is_builder_request(conversation_id):
    return isinstance(conversation_id, str) and conversation_id.startswith(BUILDER_REQUEST_PREFIX)


class PublicationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subdomain: str = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    node_id: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)

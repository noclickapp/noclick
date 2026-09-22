"""The requested outcome of a builder run, independent of its caller."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BUILDER_REQUEST_PREFIX = "builder-request:"


def is_builder_request(conversation_id):
    return isinstance(conversation_id, str) and conversation_id.startswith(BUILDER_REQUEST_PREFIX)


class PublicationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["publish", "rename", "unpublish"] = "publish"
    subdomain: str | None = Field(default=None, min_length=3, max_length=63,
                                 pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
                                 description="New address. Omit when republishing at the existing address.")
    node_id: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "rename" and not self.subdomain:
            raise ValueError("Renaming requires a new subdomain.")
        if self.action == "unpublish" and self.subdomain:
            raise ValueError("Unpublish uses the existing address; omit subdomain.")
        if self.action != "publish" and self.title:
            raise ValueError("Only publish can change the title.")
        return self

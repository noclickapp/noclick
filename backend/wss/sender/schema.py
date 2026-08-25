"""
Pydantic models used by socket events but not events themselves.
These are supporting data structures that provide type safety and validation.
"""
from typing import Optional, List, Literal, Union

from pydantic import BaseModel, Field


class ImageUrl(BaseModel):
    """Structured image reference with optional metadata."""
    url: str
    detail: Optional[str] = None
    format: Optional[str] = None

    def to_litellm_payload(self) -> dict:
        payload = {"url": self.url}
        if self.detail:
            payload["detail"] = self.detail
        if self.format:
            payload["format"] = self.format
        return payload


class ContentItem(BaseModel):
    """Single content item in a sequence-sensitive message."""
    type: Literal["text", "image_url", "video_url"]
    text: Optional[str] = None
    image_url: Optional[Union[str, ImageUrl]] = None
    # Generated-media video reference (image/video/kling output models). Plain
    # URL — video is a display-only output, never fed back as agent input, so
    # it needs none of ImageUrl's litellm detail/format metadata.
    video_url: Optional[str] = None
    metadata: Optional[dict] = Field(
        None,
        description="Optional metadata for the content item (e.g., drawing info, HTML type)"
    )

    def get_image_url(self) -> Optional[str]:
        """Return the raw URL string if this item references an image."""
        if isinstance(self.image_url, ImageUrl):
            return self.image_url.url
        return self.image_url

    def get_image_payload(self) -> Optional[dict]:
        """Return the LiteLLM-compatible image payload for structured image entries."""
        if self.type != "image_url" or not self.image_url:
            return None
        if isinstance(self.image_url, ImageUrl):
            return self.image_url.to_litellm_payload()
        return None

    def is_drawing(self) -> bool:
        """Check if this content item is a drawing/annotation."""
        return bool(self.metadata and self.metadata.get('is_drawing'))

    def get_drawing_id(self) -> Optional[str]:
        """Get the drawing ID if this is a drawing."""
        if self.is_drawing() and self.metadata:
            return self.metadata.get('drawing_id')
        return None

class AgenticStep(BaseModel):
    """
    Represents a step in an agentic workflow.
    
    Used for tracking multi-step AI agent operations with nested sub-steps.
    """
    id: str = Field(..., description="Unique identifier for the step")
    text: str = Field(..., description="Description of what this step does")
    status: str = Field(default='pending', description="Status: pending|in_progress|completed")
    sub_steps: Optional[List['AgenticStep']] = Field(None, description="Optional nested sub-steps")


# Enable forward references for recursive model
AgenticStep.model_rebuild()

"""Responses of the phone-number purchase events. A separate module so the
engine's handler can import them in every edition; ``wss.sender.responses``
re-exports them for type generation."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class PhoneNumberSearchResponse(BaseModel):
    """Response for phone_number:search"""
    numbers: List[Dict[str, Any]] = Field(default_factory=list, description="Available numbers: phone_number, locality, region, capabilities")
    monthly_credits: int = Field(..., description="What a number costs per month, in credits")


class PhoneNumberBuyResponse(BaseModel):
    """Response for phone_number:buy"""
    credential_id: str = Field(..., description="The phone_number credential that now holds the number")
    phone_number: str = Field(..., description="The bought number, E.164")

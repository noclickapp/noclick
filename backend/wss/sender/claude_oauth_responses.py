"""Shared Claude sign-in responses for both editions.

Keeps failure/restart semantics identical across socket and public sign-in UI.
"""
from typing import Optional
from pydantic import BaseModel, Field


class ClaudeCodeAuthStartResponse(BaseModel):
    """Response for claude-code:auth:start"""

    success: bool = Field(..., description="Whether the OAuth start was successful")
    auth_url: Optional[str] = Field(
        None, description="URL to open in browser for authentication"
    )
    auth_session_id: Optional[str] = Field(
        None, description="Session ID for exchanging the code"
    )
    message: Optional[str] = Field(None, description="Status or error message")
    error_code: Optional[str] = None


class ClaudeCodeAuthExchangeResponse(BaseModel):
    """Response for claude-code:auth:exchange"""

    success: bool = Field(..., description="Whether the code exchange was successful")
    credential_id: Optional[str] = Field(
        None, description="UUID of the created credential"
    )
    credential_name: Optional[str] = Field(
        None, description="Name of the created credential"
    )
    message: Optional[str] = Field(None, description="Status or error message")
    error_code: Optional[str] = None
    restart_required: bool = False

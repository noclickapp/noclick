"""Responses of ``whatsapp:agent:*``: the agent of a WhatsApp number the account linked for itself."""

from typing import Optional

from pydantic import BaseModel, Field


class WhatsAppNumberAgent(BaseModel):
    """The agent answering a WhatsApp number, and its channel in Work"""
    agent_id: str = Field(..., description="The agent's id")
    name: str = Field(..., description="The agent's name")
    channel_id: Optional[str] = Field(None, description="Its own channel's id, where the owner talks to it")
    channel_name: Optional[str] = Field(None, description="Its own channel's name")


class WhatsAppAgentStatusResponse(BaseModel):
    """Response for whatsapp:agent:status — whether the number may be offered an agent, and the one answering it"""
    success: bool = Field(..., description="Whether the read succeeded")
    available: bool = Field(False, description="Whether this account can put an agent on the number")
    agent: Optional[WhatsAppNumberAgent] = Field(None, description="The agent already answering the number")
    message: Optional[str] = Field(None, description="Error message")


class WhatsAppAgentCreateResponse(BaseModel):
    """Response for whatsapp:agent:create — the number's agent, made, or the one already answering it"""
    success: bool = Field(..., description="Whether the number has its agent now")
    created: bool = Field(False, description="False when an agent already answered the number and none was made")
    agent: Optional[WhatsAppNumberAgent] = Field(None, description="The number's agent and its channel")
    message: Optional[str] = Field(None, description="Error message")

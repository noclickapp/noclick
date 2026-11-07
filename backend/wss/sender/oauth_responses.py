"""Standard OAuth response models shared by the hosted and open editions."""
from typing import Optional

from pydantic import BaseModel


class OAuthExchangeResponse(BaseModel):
    """Response for oauth:exchange request"""
    success: bool
    credential_id: Optional[str] = None
    credential_name: Optional[str] = None
    name: Optional[str] = None
    message: Optional[str] = None


class OAuthRefreshResponse(BaseModel):
    """Response for oauth:refresh request"""
    success: bool
    expires_at: Optional[str] = None
    message: Optional[str] = None


class OAuthValidateResponse(BaseModel):
    """Response for oauth:validate request"""
    valid: bool
    expired: bool = False
    message: Optional[str] = None

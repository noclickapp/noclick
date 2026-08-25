"""Provider-neutral metering event shape."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, validator


UsageType = Literal[
    "ai_usage", "ai_builder", "ai_testing", "cpu_usage", "gpu_usage", "api_usage"
]
UnitType = Literal[
    "tokens", "cpu_hours", "gpu_hours", "requests", "mb", "gb_hours", "seconds"
]


class UsageEventData(BaseModel):
    """One observed unit of work, independent of charging or plan policy."""

    user_id: str = Field(..., description="User UUID for access scoping")
    total_cost: Decimal = Field(..., ge=0, description="Observed cost in dollars")
    usage_type: UsageType
    usage_subtype: str
    quantity: Decimal = Field(..., ge=0)
    unit_type: UnitType
    user_resource: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
    organization_id: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[datetime] = None

    @validator("organization_id")
    def normalize_organization_id(cls, value):
        if value is not None and not str(value).strip():
            return None
        return value

    @validator("metadata")
    def validate_metadata(cls, value):
        json.dumps(value)
        return value

    @validator("user_id")
    def validate_user_id(cls, value):
        if not value or len(value) < 10:
            raise ValueError("user_id must be a valid UUID string")
        return value

    def to_db_params(
        self,
        include_id: bool = False,
        topup_window_start=None,
        now=None,
    ) -> tuple:
        """Return parameters for the generic usage-events table.

        The trailing arguments are accepted only for source compatibility with
        external extensions compiled against an older interface.
        """
        del topup_window_start, now
        params = (
            self.user_id,
            float(self.total_cost),
            self.usage_type,
            self.usage_subtype,
            float(self.quantity),
            self.unit_type,
            self.user_resource,
            json.dumps(self.metadata) if self.metadata else "{}",
            self.organization_id,
        )
        return (self.id,) + params if include_id and self.id else params

"""The shape of a usage event.

One definition for every edition: what a metered action records is a property
of the engine, not of whoever is billing for it. Where the event goes — a
ledger, a log line, nowhere — is the platform's business.
"""

from typing import Dict, Any, Optional, Union, Literal
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field, validator
import json

from .markup import CREDITS_PER_DOLLAR  # noqa: F401 — re-exported for ledger math

# The ledger SQL below converts the event's $ cost to credits (and back) using
# this factor. Interpolated from the single source of truth in markup.py at
# import time so the write-side ledger math can't silently diverge from the
# read-side conversion if the conversion rate ever changes. Rendered as a plain
# numeric literal (e.g. "4") into the query string.
_CPD = CREDITS_PER_DOLLAR


# Type aliases for better clarity.
#
# `ai_builder` is the workflow-graph generation / agentic edit path
# (workflow_builder_handler._store_builder_usage_event). It writes the
# customer-facing $ cost after the configured AI builder adjustment so the
# read-side cap math (plan_limits.get_credit_usage) can convert
# uniformly via CREDITS_PER_DOLLAR.
#
# Without 'ai_builder' in the Literal, every agentic-builder turn fails
# Pydantic validation, the exception is swallowed by the warning catch
# in _store_builder_usage_event, and no row is written — credits never
# decrement and the chip stays at full balance.
UsageType = Literal["ai_usage", "ai_builder", "ai_testing", "cpu_usage", "gpu_usage", "api_usage"]
UnitType = Literal["tokens", "cpu_hours", "gpu_hours", "requests", "mb", "gb_hours", "seconds"]


class UsageEventData(BaseModel):
    """
    Schema for user_usage_events table row.

    Matches the database schema and provides type safety for insertions.
    """

    # Required fields
    user_id: str = Field(..., description="UUID of the user")
    total_cost: Decimal = Field(..., ge=0, description="Total cost in dollars (e.g., 0.0005 = $0.0005)")
    usage_type: UsageType = Field(..., description="Type of usage")
    usage_subtype: str = Field(..., description="Specific subtype (model, instance type, etc.)")

    # Usage metrics
    quantity: Decimal = Field(..., ge=0, description="Amount used (tokens, hours, etc.)")
    unit_type: UnitType = Field(..., description="Unit of measurement")

    # Billing flag
    user_resource: bool = Field(False, description="True if user's own resource")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    # Organization billing
    organization_id: Optional[str] = Field(None, description="Organization ID if org workflow (charges org balance)")

    # Optional fields (can be provided or auto-generated)
    id: Optional[str] = Field(None, description="UUID - can be provided or auto-generated")
    created_at: Optional[datetime] = Field(None, description="Auto-generated timestamp")

    @validator('organization_id')
    def normalize_organization_id(cls, v):
        """Coerce empty/whitespace organization_id to None.

        The Owner-Pays choke point keys on a truthy organization_id. A buggy
        caller passing "" (e.g. dict.get('id', '')) would otherwise be treated
        as personal work and silently bill the running member instead of the org
        owner. Normalizing here closes that gap at the schema boundary so every
        write path is safe regardless of how the caller built the value.
        """
        if v is not None and not str(v).strip():
            return None
        return v

    @validator('metadata')
    def validate_metadata(cls, v):
        """Ensure metadata is JSON serializable"""
        if v is not None:
            try:
                json.dumps(v)
            except (TypeError, ValueError) as e:
                raise ValueError(f"Metadata must be JSON serializable: {e}")
        return v

    @validator('user_id')
    def validate_user_id(cls, v):
        """Basic UUID format validation"""
        if not v or len(v) < 10:
            raise ValueError("user_id must be a valid UUID string")
        return v

    def to_db_params(
        self,
        include_id: bool = False,
        topup_window_start=None,
        now=None,
    ) -> tuple:
        """Convert to database parameters tuple for insertion.

        Args:
            include_id: If True, includes the id field at the beginning of the tuple.
            topup_window_start: Lower bound of the CURRENT topup monthly window
                (from plan_limits.topup_window_start), used by the INSERT to derive
                this event's topup_paid from SUM(topup_paid in window) — so a yearly
                topup's monthly reset is actually spendable. None when the user has
                no active topup (the INSERT then allocates 0 to topup).
            now: billing_now() — used for the coverage-expiry check and as the row's
                created_at, so a dev Stripe test clock drives both. None → the INSERT
                falls back to SQL NOW() (prod real clock).

        The two trailing params are appended in the same order both INSERT
        variants expect.
        """
        base_params = (
            self.user_id,
            float(self.total_cost),  # Convert Decimal to float for database
            self.usage_type,
            self.usage_subtype,
            float(self.quantity),  # Convert Decimal to float for database
            self.unit_type,
            self.user_resource,
            json.dumps(self.metadata) if self.metadata else '{}',
            self.organization_id,
        )

        if include_id and self.id:
            return (self.id,) + base_params + (topup_window_start, now)
        return base_params + (topup_window_start, now)

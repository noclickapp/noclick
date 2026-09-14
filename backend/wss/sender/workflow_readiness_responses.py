"""Typed readiness evidence shared by setup and agent introspection.

Registration and retained input are evidence, never a delivery/read receipt.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ReadinessIssue(BaseModel):
    node_id: str
    code: str
    message: str


class TriggerObservation(BaseModel):
    node_id: str
    execution_id: str
    created_at: str
    trigger_source: str
    run_status: str


class AlertDestination(BaseModel):
    node_id: str
    operation: str
    recipients: list[str]


class DeadlineWatchEvidence(BaseModel):
    node_id: str
    watch_key: str
    status: str
    deadline: str
    last_seen_at: Optional[str] = None
    fired_at: Optional[str] = None


class WorkflowReadinessReport(BaseModel):
    status: Literal[
        "needs_setup",
        "configured",
        "waiting_for_input",
        "deadline_armed",
        "input_observed",
        "manual_only",
    ]
    issues: list[ReadinessIssue]
    registered_trigger_ids: list[str]
    observations: list[TriggerObservation]
    destinations: list[AlertDestination]
    deadline_watches: list[DeadlineWatchEvidence] = Field(default_factory=list)
    alarm_node_ids: list[str] = Field(default_factory=list)
    explanation: str

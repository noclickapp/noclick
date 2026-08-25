"""Operator-neutral model selection for the community edition."""

from __future__ import annotations


def apply_model_substitution(
    model: str,
    workflow_id: str | None = None,
    node_id: str | None = None,
    user_id: str | None = None,
    user_email: str | None = None,
) -> str:
    del workflow_id, node_id, user_id, user_email
    return model


def notify_missing_cost(model: str) -> None:
    del model

"""Which ``workflow_executions`` rows a user should see.

Agent delivery runs are hidden plumbing: they persist as ``delivered`` rows so
their outputs survive, but no listing counts or shows them. This module is
shared by both editions so every listing applies the same rule.
"""

DELIVERED_STATUS = "delivered"
USER_VISIBLE_RUN_SQL = f"status <> '{DELIVERED_STATUS}'"

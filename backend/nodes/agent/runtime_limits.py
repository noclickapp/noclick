"""Execution bounds shared by community-edition modules."""

# First-response tool-call recovery uses a conservative four-hour lookback when
# no prior response boundary exists. Keeping the fallback here avoids coupling
# shared logging code to any particular execution backend.
TURN_TOOL_LOOKBACK_S = 4 * 3600

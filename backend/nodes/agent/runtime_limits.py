"""Agent runtime bounds that shipped modules need.

A warm-sandbox runtime keeps a turn's tool capability and bundle alive for the
sandbox's whole life, and the tool-call log windows its turn boundary on that
lifetime. Those bounds are read by modules that ship — the agent node mints
the capability, the log windows on it — so they live here, on the open side
of the seam, and the hosted timeout module re-exports them so its invariants
stay asserted in one place.
"""

WARM_HARD_TIMEOUT_S = 4 * 3600

# How far back a turn's tool calls are attributed to it.
TURN_TOOL_LOOKBACK_S = WARM_HARD_TIMEOUT_S

# A turn's tool capability must outlive the sandbox that holds it (the token is
# written into the harness config once at cold start and never re-read).
SHADOW_TOKEN_TTL_HOURS = 6      # > WARM_HARD_TIMEOUT_S (4h) + margin
SHADOW_BUNDLE_TTL_S = 6 * 3600  # same bound; the bundle is the token's other half

// Single source of truth for deriving an agent node's "still processing in its
// sandbox" state from its hydrated data + live sandbox presence. A delivered turn
// ('awaiting_agent_turn' output) must read as running only while there is reason to
// believe the turn is alive: a lost turn (its process gone, its callback never sent)
// leaves the marker as the node's latest stored output, and an ungated check would
// draw a running animation forever on every canvas load. Consumed by withNodeWrapper
// (aurora/chrome) and an agent node's own spinner so the two never diverge.

import { useEffect, useReducer } from 'react';

import type { NodeAgentPresence } from './agentPresenceStore';

/** Presence-absent trust bound. NOT a turn timeout — a coding agent's turn can run for
 *  hours, and live presence (busy) extends past this indefinitely. This only caps how
 *  long a marker with NO liveness signal keeps animating; the server settles what's
 *  stored. */
export const AWAITING_TURN_FRESH_MS = 30 * 60 * 1000;

export interface AgentRunStateData {
  output?: { status?: string };
  _lastRunAt?: number;
}

/**
 * True while an AGENT node's latest output is an awaiting-turn delivery marker that
 * we still have reason to trust (callers gate on node type — this reads purely
 * data + presence → bool):
 *
 * 1. Live presence BUSY (pushed off the sandbox's heartbeat) → running. Positive
 *    liveness beats any staleness heuristic.
 * 2. Otherwise → time-bounded trust via _lastRunAt (the live path stamps Date.now()
 *    at a terminal state; a load carries the time the output was stored).
 *    outputTimestamp cannot be the gate — a cold load sets it to load time, which
 *    always looks fresh.
 *
 * Deliberately NO "presence reports zero sandboxes → cut early" rule: presence drops
 * a node after missed heartbeats, so count 0 also means "heartbeats degraded" —
 * cutting on it would flip a LIVE turn to idle mid-flight. Dead markers are the
 * server's to settle.
 */
export function isAwaitingAgentTurn(
  data: AgentRunStateData | undefined,
  presence?: NodeAgentPresence,
): boolean {
  if (data?.output?.status !== 'awaiting_agent_turn') return false;
  if (presence?.busy) return true;
  return (
    typeof data._lastRunAt === 'number' &&
    Date.now() - data._lastRunAt < AWAITING_TURN_FRESH_MS
  );
}

/**
 * Hook form: isAwaitingAgentTurn + a scheduled re-render when the marker crosses
 * the freshness bound. Render-time Date.now() alone never re-evaluates on an
 * already-open canvas with no presence deltas (where presence isn't reported, which
 * the time bound exists for) — the spinner would outlive the bound indefinitely.
 */
export function useAwaitingAgentTurn(
  data: AgentRunStateData | undefined,
  presence?: NodeAgentPresence,
): boolean {
  const [, bump] = useReducer((c: number) => c + 1, 0);
  const lastRunAt = data?._lastRunAt;
  const hasMarker = data?.output?.status === 'awaiting_agent_turn';
  const busy = presence?.busy === true;
  useEffect(() => {
    if (!hasMarker || busy || typeof lastRunAt !== 'number') return;
    const untilStale = AWAITING_TURN_FRESH_MS - (Date.now() - lastRunAt);
    if (untilStale <= 0) return; // already past the bound — nothing to schedule
    const timer = setTimeout(bump, untilStale + 50);
    return () => clearTimeout(timer);
  }, [hasMarker, busy, lastRunAt]);
  return isAwaitingAgentTurn(data, presence);
}

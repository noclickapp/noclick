// Shared event name for the one-time "find the invite link" walkthrough.
// The inline invite banner (InviteBanner) dispatches this when dismissed;
// FlowCanvas listens and shows the GuidedTourHighlight. The per-user "seen"
// state is NOT stored here — it lives in the generic, server-backed, cross-device
// seen-once store (app/hooks/useSeenOnce.ts, key 'invite_walkthrough'), written
// only once the tour actually completes.

// Document-level CustomEvent that asks the canvas to show the walkthrough.
export const INVITE_WALKTHROUGH_EVENT = 'noclick:invite:show-walkthrough';

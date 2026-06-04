// Shared constants for the collaborative workflow invite-link flow.
// Kept in a server-free module so both the /i/<token> route and the client-side
// WorkflowBrowser can import the sessionStorage key without dragging server-only
// code into the client bundle.

// sessionStorage key holding a pending invite token between the /i/<token>
// landing and the dashboard, where WorkflowBrowser redeems it and opens the
// shared flow.
export const PENDING_INVITE_KEY = 'noclick_pending_invite';

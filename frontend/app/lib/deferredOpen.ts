// Keys of the "deferred-open" carry-overs a public page stashes in sessionStorage
// before routing the visitor to /dashboard, where WorkflowBrowser materializes
// them once the socket connects (the invite and scaffold keys live beside their
// writers in inviteLink / agentScaffold).
//
// Kept server-free so it rides the authed app bundle. Deliberately NOT imported
// by perf-sensitive public/landing routes, whose writers mirror these strings.

// Writer lives in PublicWorkflowView (template fork deferred-open).
export const FORK_DATA_KEY = 'noclick_fork_workflow_data';
// Writer lives in the landing hero + integration connect pages.
export const HERO_PROMPT_KEY = 'noclick:hero-prompt';

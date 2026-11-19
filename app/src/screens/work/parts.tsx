// The views other parts of Work draw, at the props the page mounts them with: the Agents list, an agent's
// session, profile, machine and draft, and a space's resources.
export { AgentsList } from './agents/AgentsList';
export { AgentConversation } from './conversation/AgentConversation';
export { prefetchConversation } from './conversation/useConversation';
export { useFollowSessions, useSessions } from './conversation/sessions';
export { AgentProfile } from './profile/AgentProfile';
export { NewAgent } from './newAgent/NewAgent';
export { MachinePage } from './machine/MachinePage';
export { SpaceResourcesNav, SpaceResourcesPane } from './resources/SpaceResources';

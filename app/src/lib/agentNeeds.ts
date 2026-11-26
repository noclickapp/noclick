// What an agent made for some apps waits on before it can start, as the platform names it: POST
// /v1/agents/for_apps's `needs`, the note the chat keeps of the agent's arrival, and its channel message's `connect`
// event. An account of one of its apps, or its model.

export type AgentNeed = { kind: 'app'; integration: string; node_type: string; label: string; description?: string | null } | { kind: 'model' };

/** A need as the platform keeps it; null for anything that isn't one. */
export function needOf(raw: unknown): AgentNeed | null {
    const n = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null;
    if (n?.kind === 'model') return { kind: 'model' };
    if (n?.kind !== 'app' || typeof n.integration !== 'string' || typeof n.node_type !== 'string') return null;
    return { kind: 'app', integration: n.integration, node_type: n.node_type, label: typeof n.label === 'string' ? n.label : n.integration, description: typeof n.description === 'string' ? n.description : null };
}

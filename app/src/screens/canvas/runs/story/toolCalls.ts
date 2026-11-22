// The tool calls an agent made in a run, as its results list them: each call with what it was given, how it ended and
// how long it took.

export interface ReplayToolCall {
    agent_node_id: string | null;
    tool_name: string;
    tool_type: string;
    provider_node_id: string | null;
    operation: string | null;
    credential_id: string | null;
    arguments: Record<string, unknown> | null;
    result_status: string;
    error: string | null;
    result_preview: string | null;
    duration_ms: number | null;
    timestamp: string | null;
}

// Map an agent output's embedded `tool_calls` package — recorded with the turn
// and attached to the output of the run that answers it — into ReplayToolCall
// rows. An agent that takes its turn in its own sandbox records its calls under
// the turn, not under that run, so the package is the only source for them; an
// agent that runs in the workflow's own process carries no package, and its
// calls come from the run's record where the host reads one.
// The package uses `created_at`; the rows carry `timestamp`.
export function toReplayToolCalls(output: unknown): ReplayToolCall[] {
    if (!output || typeof output !== 'object') return [];
    const raw = (output as Record<string, unknown>).tool_calls;
    if (!Array.isArray(raw)) return [];
    return raw.map((c) => {
        const t = (c ?? {}) as Record<string, unknown>;
        return {
            agent_node_id: (t.agent_node_id as string) ?? null,
            tool_name: String(t.tool_name ?? ''),
            tool_type: String(t.tool_type ?? ''),
            provider_node_id: (t.provider_node_id as string) ?? null,
            operation: (t.operation as string) ?? null,
            credential_id: (t.credential_id as string) ?? null,
            arguments: (t.arguments as Record<string, unknown>) ?? null,
            result_status: String(t.result_status ?? 'success'),
            error: (t.error as string) ?? null,
            result_preview: (t.result_preview as string) ?? null,
            duration_ms:
                typeof t.duration_ms === 'number' ? t.duration_ms : null,
            timestamp:
                (t.created_at as string) ?? (t.timestamp as string) ?? null,
        };
    });
}

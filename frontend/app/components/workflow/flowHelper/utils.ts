// Extract operation from node data. All node schemas use 'operation' as the
// canonical discriminator field.
export function getNodeOperation(nodeData: Record<string, unknown>): string {
    return (nodeData?.operation as string) || 'default';
}

// Verbose relative-time format used by the flow helper's history carousels
// ("3h ago", "just now", falls back to a locale date for anything a week old).
// Distinct from the shorter format used in WorkflowCheckpointControl, so kept
// local to this module.
export function formatRelativeTime(isoString: string): string {
    const date = new Date(isoString);
    const now = Date.now();
    const diffMs = now - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return 'just now';
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDays = Math.floor(diffHr / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

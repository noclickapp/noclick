// Observes the in-flight n8n workflow import so any UI surface (prompt input,
// chat sidebar header, etc.) can render the N8nImportBadge without plumbing
// the detection state through props. Paired with noclick:n8n:import:start/end
// events dispatched by FlowCanvas when a paste is recognized and when the
// agentic edit finishes.

import { useEffect, useState } from 'react';

export interface N8nImportStatus {
    /** Non-null while an n8n import is in progress (paste recognized, edit running). */
    nodeCount: number | null;
}

export function useN8nImportStatus(): N8nImportStatus {
    const [nodeCount, setNodeCount] = useState<number | null>(null);

    useEffect(() => {
        const onStart = (e: Event) => {
            const detail = (e as CustomEvent<{ nodeCount?: number }>).detail;
            setNodeCount(detail?.nodeCount ?? 0);
        };
        const onEnd = () => setNodeCount(null);

        document.addEventListener('noclick:n8n:import:start', onStart);
        document.addEventListener('noclick:n8n:import:end', onEnd);
        return () => {
            document.removeEventListener('noclick:n8n:import:start', onStart);
            document.removeEventListener('noclick:n8n:import:end', onEnd);
        };
    }, []);

    return { nodeCount };
}

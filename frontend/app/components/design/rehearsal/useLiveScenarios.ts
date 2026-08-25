/* Fetches what THIS workflow can rehearse — the backend derives it from the
   saved graph, so the Test screen's pickers are real controls fed by real data.
   The response is mapped into the TriggerFixture shape the screen already
   renders, with the backend's scenario key riding along for rehearsal:run. */

import { useEffect, useState } from 'react';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { RehearsalScenariosRequest, sendEventAsync } from '~/lib/socket-sender';
import type { Provider, TriggerFixture } from './fixture';

/** Display identity per trigger node type. Grows with the backend registry. */
const NODE_TYPE_META: Record<
    string,
    { provider: Provider | 'generic'; nodeName: string; label: string }
> = {
    'automation-gmail': { provider: 'gmail', nodeName: 'Gmail', label: 'Staged email' },
    'automation-slack': { provider: 'slack', nodeName: 'Slack', label: 'Staged message · Slack' },
    'automation-whatsapp': {
        provider: 'whatsapp',
        nodeName: 'WhatsApp',
        label: 'Staged message · WhatsApp',
    },
    'automation-telegram': {
        provider: 'telegram',
        nodeName: 'Telegram',
        label: 'Staged message · Telegram',
    },
};

function prettifyNodeType(nodeType: string): string {
    return nodeType
        .replace(/^(automation|trigger)-/, '')
        .split('-')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');
}

export interface LiveScenarios {
    loading: boolean;
    triggers: TriggerFixture[];
    error: string | null;
}

export function useLiveScenarios(workflowId: string | null): LiveScenarios {
    const [state, setState] = useState<LiveScenarios>({
        loading: Boolean(workflowId),
        triggers: [],
        error: null,
    });

    useEffect(() => {
        if (!workflowId) return;
        let cancelled = false;
        (async () => {
            try {
                const res: any = await sendEventAsync(
                    RehearsalScenariosRequest.create({ workflow_id: workflowId })
                );
                if (cancelled) return;
                if (!res?.success) {
                    setState({
                        loading: false,
                        triggers: [],
                        error: res?.message || 'Could not list rehearsable situations.',
                    });
                    return;
                }
                const triggers: TriggerFixture[] = (res.triggers ?? [])
                    .map((t: any) => {
                        // Unknown types keep GENERIC semantics (raw-JSON
                        // scenario, no editing) but wear their own catalog
                        // identity — real display name, real logo via
                        // iconSlug — because "your trigger is rehearsable
                        // today" beats waiting for a native rendering, and a
                        // prettified type string under an amber bolt read as
                        // unsupported (the cal.com report).
                        const def = AVAILABLE_NODES.find((n) => n.type === t.node_type);
                        const meta = NODE_TYPE_META[t.node_type] ?? {
                            provider: 'generic' as const,
                            nodeName: def?.label ?? prettifyNodeType(t.node_type),
                            label: 'Staged event',
                        };
                        return {
                            slug: t.node_type,
                            name: meta.nodeName,
                            nodeName: meta.nodeName,
                            triggerLabel: meta.label,
                            provider: meta.provider,
                            operation: t.operation ?? undefined,
                            iconSlug: t.node_type
                                .replace(/^automation-/, '')
                                .replace(/-/g, '_'),
                            mocks: (t.situations ?? []).map((s: any) => ({
                                slug: s.key,
                                backendKey: s.key,
                                name: s.name,
                                lead: s.lead,
                                events: [],
                                doneAt: 0,
                                artifacts: null,
                            })),
                        };
                    })
                    .filter(Boolean) as TriggerFixture[];
                setState({ loading: false, triggers, error: null });
            } catch (e) {
                if (!cancelled) {
                    setState({
                        loading: false,
                        triggers: [],
                        error: e instanceof Error ? e.message : String(e),
                    });
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [workflowId]);

    return state;
}

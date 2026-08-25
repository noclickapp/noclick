// Runs an agent against a staged world and streams back what it did.
//
// The agent, model and prompt are real; only the world is fabricated (see
// backend/nodes/agent/REHEARSAL.md). That distinction has to survive all the way
// to the screen: a rehearsal demonstrates BEHAVIOUR and proves nothing about
// connectivity, so this hook always reports `rehearsed: true` and never lets a
// caller present the result as evidence that a credential works.

import { useCallback, useEffect, useRef, useState } from 'react';
import { onSocketEvent } from '~/lib/socket-receiver';
import { sendEventAsync, RehearsalRunRequest } from '~/lib/socket-sender';

export interface RehearsalStep {
    id: string;
    /** What the agent did, in the user's terms. */
    text: string;
    status: 'in_progress' | 'completed';
    /** The tool's own name, when this step was a tool call. */
    tool?: string;
    /** Display name of the service it reached for, when there was one. */
    provider?: string;
    /** When this row first appeared (client clock). */
    startedAt: number;
    /** How long the step took, measured client-side between its in_progress and
        completed frames. Honest data — not a fabricated duration — which is why
        it is measured here rather than invented by the mock. */
    ms?: number;
}

export type RehearsalPhase = 'idle' | 'running' | 'done' | 'failed';

/** Turn `slack__send_message_to_channel` into something a person would say.
    This line is read by someone deciding whether to trust the agent, so the
    verb and the provider matter and the raw tool name does not. */
// Brands whose casing a title-case pass gets wrong. Everything else is
// title-cased from the slug, so a new provider reads correctly without an entry.
const PROVIDER_NAMES: Record<string, string> = {
    github: 'GitHub',
    gitlab: 'GitLab',
    hubspot: 'HubSpot',
    linkedin: 'LinkedIn',
    youtube: 'YouTube',
    tiktok: 'TikTok',
    wordpress: 'WordPress',
    whatsapp: 'WhatsApp',
    pagerduty: 'PagerDuty',
    quickbooks: 'QuickBooks',
    bamboohr: 'BambooHR',
    dv360: 'DV360',
    onedrive: 'OneDrive',
    bigquery: 'BigQuery',
    clickup: 'ClickUp',
    'cal com': 'Cal.com',
    'github rest': 'GitHub',
    'google sheets': 'Google Sheets',
    'google drive': 'Google Drive',
    'google calendar': 'Google Calendar',
    'google docs': 'Google Docs',
};

function providerName(slug: string): string {
    const spaced = slug.replace(/_/g, ' ').trim();
    const known = PROVIDER_NAMES[spaced] ?? PROVIDER_NAMES[spaced.replace(/\s+/g, '')];
    if (known) return known;
    return spaced.replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

export function readableStep(toolName: string): {
    label: string;
    provider?: string;
    tool?: string;
} {
    const tool = (toolName || '').trim();
    if (!tool) return { label: 'Working…' };
    const [head, ...rest] = tool.split('__');
    const rawAction = (rest.join('__') || head).replace(/_/g, ' ').trim();
    // Sentence case, not Title Case: this sits in a list a person reads, not a
    // menu they scan, and Title Case On Every Row reads like a spreadsheet.
    const action = rawAction.charAt(0).toUpperCase() + rawAction.slice(1);
    return {
        label: action,
        provider: rest.length ? providerName(head) : undefined,
        tool,
    };
}

export function useRehearsal(workflowId: string | null, scenario = 'sales-inbound-lead') {
    const [phase, setPhase] = useState<RehearsalPhase>('idle');
    const [steps, setSteps] = useState<RehearsalStep[]>([]);
    const [reply, setReply] = useState('');
    // What the agent actually composed, taken from the tool call it made. The
    // agent's closing text is a report addressed to the user; this is the work.
    const [posted, setPosted] = useState('');
    const [error, setError] = useState<string | null>(null);
    const conversationRef = useRef<string | null>(null);

    // The rehearsal carries its own channel. Chat frames route through the
    // workflow room, and a surface that never opened the workflow — onboarding,
    // a template preview — is not in that room, so those frames never arrive.
    //
    // Subscribed for the whole lifetime rather than only while running, so a
    // frame is never dropped for want of a listener.
    useEffect(() => {
        return onSocketEvent('rehearsal:progress' as never, ((data: any) => {
            if (!data || data.conversation_id !== conversationRef.current) return;

            if (data.kind === 'step' && data.step_id) {
                const { label, tool, provider } = readableStep(data.tool || '');
                setSteps((prev) => {
                    const next = [...prev];
                    const at = next.findIndex((s) => s.id === data.step_id);
                    const before = at >= 0 ? next[at] : null;
                    const completed = data.status === 'completed';
                    const startedAt = before?.startedAt ?? Date.now();
                    const row: RehearsalStep = {
                        id: data.step_id,
                        text: label,
                        status: completed ? 'completed' : 'in_progress',
                        tool,
                        provider,
                        startedAt,
                        // An orphaned completed frame (its in_progress never arrived)
                        // gets no duration rather than a fabricated ~0ms one.
                        ms: completed && before ? Date.now() - startedAt : undefined,
                    };
                    if (at >= 0) next[at] = row;
                    else next.push(row);
                    return next;
                });
                if (typeof data.outbound === 'string' && data.outbound.trim()) {
                    setPosted(data.outbound.trim());
                }
                return;
            }

            if (data.kind === 'done') {
                setReply(data.reply || '');
                setPhase('done');
            } else if (data.kind === 'failed') {
                setError(data.error || 'The rehearsal did not finish.');
                setPhase('failed');
            }
        }) as never);
    }, []);

    const run = useCallback(async () => {
        if (!workflowId) return;
        setPhase('running');
        setSteps([]);
        setReply('');
        setPosted('');
        setError(null);
        try {
            const res: any = await sendEventAsync(
                RehearsalRunRequest.create({ workflow_id: workflowId, scenario })
            );
            if (!res?.success) {
                setError(res?.message || 'The rehearsal could not start.');
                setPhase('failed');
                return;
            }
            conversationRef.current = res.conversation_id;
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
            setPhase('failed');
        }
    }, [workflowId, scenario]);

    return { phase, steps, reply, posted, error, run, rehearsed: true as const };
}

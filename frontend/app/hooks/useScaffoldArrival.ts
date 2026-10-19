// Someone who set an agent up on a public page (an /agents page, /mcp) lands in the chat signed in: make the
// workflow, attach the accounts they already have (as adding a node on the canvas does), then have NoClick post it
// to the thread, where its setup card takes over. Once per stash; a bare scaffold is the Automations page's.
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useOrgContext } from '~/hooks/useOrgContext';
import { PENDING_SCAFFOLD_KEY, clearScaffoldIntent, readScaffoldIntent, type ScaffoldBlob } from '~/lib/agentScaffold';
import { clearPostOnboardingFlow } from '~/lib/deferredOpen';
import { isPlanLimitError } from '~/lib/planLimitErrors';
import { createScaffoldWorkflow, persistScaffoldOnboardingSkip } from '~/lib/scaffoldWorkflow';
import type { SetupArrival } from '~/components/shell/coordinatorChat';
import { authorizeCredentialsForWorkflow } from '~/utils/credentialAutoSelect';

async function withOwnAccounts(blob: ScaffoldBlob): Promise<ScaffoldBlob> {
    // Reads node schemas, which only an arriving workflow needs here.
    const { autoSelectCredential } = await import('~/utils/credentialAutoSelectForNode');
    const nodes = await Promise.all(
        blob.nodes.map(async (node) => {
            if (!node.type?.startsWith('automation-')) return node;
            const credentialIds = await autoSelectCredential(node.type);
            return Object.keys(credentialIds).length ? { ...node, config: { ...node.config, credentialIds } } : node;
        })
    );
    return { ...blob, nodes };
}

export interface ScaffoldArrival {
    /** Being set up: its name, and its workflow once made. Stays set after, so the page can tell when its note is in. */
    arriving: { name: string; workflowId?: string } | null;
    /** The plan refusal to show when the workflow couldn't be made, until dismissed. */
    planLimitError: string | null;
    dismissPlanLimit: () => void;
}

/** `arrive` puts NoClick's note in the thread, which draws the setup card. */
export function useScaffoldArrival(conversationId: string | null, arrive: (arrival: SetupArrival) => Promise<void>): ScaffoldArrival {
    const [orgContext] = useOrgContext();
    const [arriving, setArriving] = useState<ScaffoldArrival['arriving']>(null);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    const taken = useRef(false);
    useEffect(() => {
        if (!conversationId || taken.current) return;
        const intent = readScaffoldIntent();
        if (!intent?.setup) return;
        taken.current = true;
        clearScaffoldIntent();
        sessionStorage.removeItem(PENDING_SCAFFOLD_KEY);
        clearPostOnboardingFlow();
        persistScaffoldOnboardingSkip();
        setArriving({ name: intent.name });
        void (async () => {
            try {
                const workflowData = await withOwnAccounts(intent.workflowData);
                const workflow = await createScaffoldWorkflow({ ...intent, workflowData }, { organizationId: orgContext.id });
                setArriving({ name: workflow.name, workflowId: workflow.id });
                authorizeCredentialsForWorkflow(
                    workflow.id,
                    workflowData.nodes.flatMap((n) => Object.values((n.config.credentialIds as Record<string, string> | undefined) ?? {}))
                );
                const kind = intent.setup?.runtime === 'cloud' ? 'agent' : 'mcp';
                await arrive({ name: workflow.name, setup: { kind, workflow_id: workflow.id, client: intent.setup?.harnessSlug } });
            } catch (error) {
                setArriving(null);
                const message = error instanceof Error ? error.message : 'Could not set that up';
                if (isPlanLimitError(message)) setPlanLimitError(message);
                else toast.error(message);
            }
        })();
    }, [conversationId, orgContext.id, arrive]);
    return { arriving, planLimitError, dismissPlanLimit: () => setPlanLimitError(null) };
}

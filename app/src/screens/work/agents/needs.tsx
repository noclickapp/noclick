// What an agent made for some apps waits on before it can start (an agents page made it: POST /v1/agents/for_apps),
// as the chat's card under its note and its own first message in its channel both draw it: an account of each of its
// apps, and the model it thinks with where it had none when it was made. Each says whether it's in, read live (the
// account's connections and the agent itself, again on their frames and as an account lands here), and connects the
// way the app connects one anywhere: an app's account through its connect dialog (`connect.app`), the model through
// the AI account dialog a new agent's picker opens, the agent moved onto what landed as a conversation's account chip
// moves it (a plan onto its own harness, the model by the way that account runs it).
import { useEffect, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Check } from 'lucide-react';
import { Agent } from 'noclick';
import { useSlot } from '@/slots';
import { CONNECT_APP } from '@/ui/slots';
import { invalidateV1 } from '@/sdk/useV1';
import type { AgentNeed } from '@/lib/agentNeeds';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useWorkClient } from '../client';
import { APPS } from '../slots';
import { AGENTS_KEY } from './reads';
import { harnessLabel } from './harness';
import { accountKinds, accountTitle, namesAccount, NOCLICK_KEY, planHarness, routeFor } from '../newAgent/accounts';
import { rereadAccounts, useConnections, useHarnesses, useModelAccounts, useModelRoutes } from '../newAgent/catalog';
import { useConnectAi } from '../newAgent/ModelPicker';
import { rereadAgent, useAgent } from '../profile/reads';

/** One thing the agent waits on, as a row draws it. */
export interface NeedRow {
    key: string;
    kind: 'app' | 'model';
    /** "Roblox", "A model for Hermes". */
    title: string;
    /** What it's for while it's missing; who or what it is once it's in. */
    line: string;
    connected: boolean;
    /** The app's step type, which marks it; null for the model. */
    nodeType: string | null;
    /** Whether it can be connected from here yet (its app and the agent are read). */
    ready: boolean;
    connect: () => void;
}

export interface AgentNeeds {
    rows: NeedRow[];
    /** Nothing it waits on is missing. */
    done: boolean;
    /** The agent, once read. */
    agent: Agent | null;
    /** Its harness, as people name it ("Hermes"); null until the agent is read. */
    harness: string | null;
    /** The connect dialog open from a row. */
    dialog: ReactNode;
}

const upper = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** What `agentId` waits on of `needs` (as its note or message named them), each live. */
export function useAgentNeeds(agentId: string, needs: readonly AgentNeed[]): AgentNeeds {
    const client = useWorkClient();
    const agent = useAgent(agentId).data ?? null;
    const connections = useConnections();
    const apps = useSlot(APPS).useToolApps();
    const harnesses = useHarnesses();
    const { accounts, labels } = useModelAccounts();
    const { Connect: ConnectApp, subscribe } = useSlot(CONNECT_APP);
    const [connecting, setConnecting] = useState<string | null>(null);
    // An account connected here or in another of the page's dialogs reads again at once (its frame follows).
    useEffect(() => subscribe?.(() => rereadAccounts()), [subscribe]);

    const harness = harnesses.data?.find((h) => h.name === agent?.harness);
    const model = agent?.model ?? harness?.defaultModel ?? '';
    const { routes } = useModelRoutes(harness, model);
    const ref = agent?.modelConnection ?? null;
    const account = ref && accounts ? (accounts.find((a) => namesAccount(a, ref)) ?? null) : null;
    // On NoClick's key, or NoClick's own runtime with none, nothing of yours is needed.
    const modelIn = ref === NOCLICK_KEY || (!ref && agent?.harness === 'sdk') || !!account?.connected;

    const take = async (landed: string) => {
        if (!agent || !harness) return;
        const picked = accounts?.find((a) => a.id === landed);
        // A plan runs its own harness (a Claude plan Claude Code); a key runs the model by the way it reaches it.
        const to = picked ? planHarness(picked, harness.name) : null;
        const route = !to && picked ? routeFor(picked, harness, routes) : null;
        try {
            await Agent.fromId(agentId, { client }).update({ modelConnection: landed, ...(to ? { harness: to } : {}), ...(route && route !== agent.model ? { model: route } : {}) });
            rereadAgent(agentId);
            invalidateV1(AGENTS_KEY);
        } catch (error) {
            toast(`Couldn’t put ${agent.name} on it`, { description: errorText(error) });
        }
    };
    const connectModel = useConnectAi((landed) => void take(landed));

    const rows = needs.map((need): NeedRow => {
                if (need.kind === 'model') {
                    const name = harness ? harnessLabel(harness.name) : null;
                    return {
                        key: 'model',
                        kind: 'model',
                        title: name ? `A model for ${name}` : 'A model to think with',
                        line: modelIn ? (account ? `Runs on your ${accountTitle(account)}` : 'Runs on NoClick’s key') : harness ? upper(accountKinds(harness, model, labels)) : 'Your own key or plan',
                        connected: modelIn,
                        nodeType: null,
                        ready: !!harness && !!agent,
                        connect: () => harness && connectModel.connect(harness, model),
                    };
                }
                const held = (connections.data ?? []).find((c) => c.connected && c.userId == null && c.integration === need.integration);
                return {
                    key: `app:${need.integration}`,
                    kind: 'app',
                    title: need.label,
                    line: held ? (held.account ?? `Your ${need.label} account`) : (need.description ?? `Works in ${need.label} as you`),
                    connected: !!held,
                    nodeType: need.node_type,
                    ready: apps.some((a) => a.value === need.node_type),
                    connect: () => setConnecting(need.node_type),
                };
            });

    const open = connecting ? apps.find((a) => a.value === connecting) : undefined;
    return {
        rows,
        done: rows.length > 0 && rows.every((r) => r.connected),
        agent,
        harness: harness ? harnessLabel(harness.name) : null,
        dialog: (
            <>
                {connectModel.dialog}
                {open && (
                    <ConnectApp
                        app={open}
                        name={agent?.name ?? open.label}
                        client={client}
                        onConnected={() => {
                            rereadAccounts();
                            setConnecting(null);
                        }}
                        onClose={() => setConnecting(null)}
                    />
                )}
            </>
        ),
    };
}

/** Under an agent's message saying what it still needs (its channel's first word): a pill to connect each, a tick
 *  once it's in. */
export function NeedPills({ agentId, needs }: { agentId: string; needs: AgentNeed[] }) {
    const { rows, dialog } = useAgentNeeds(agentId, needs);
    return (
        <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="What it needs" data-testid="message-asks">
            {rows.map((row) =>
                row.connected ? (
                    <span key={row.key} className="inline-flex h-8 items-center gap-1.5 pr-2.5 text-[13px] text-muted-foreground">
                        <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.4} />
                        {row.kind === 'app' ? `${row.title} connected` : 'Model connected'}
                    </span>
                ) : (
                    <button
                        key={row.key}
                        type="button"
                        disabled={!row.ready}
                        onClick={row.connect}
                        className="inline-flex h-8 items-center rounded-full bg-primary px-3.5 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                    >
                        {row.kind === 'app' ? `Connect ${row.title}` : 'Connect a model'}
                    </button>
                )
            )}
            {dialog}
        </div>
    );
}

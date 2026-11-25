// Deleting an agent, from its profile's menu or its row in the list: the one confirm (ShellDialog with the danger pill)
// says what goes with it, as the platform previews DELETE /v1/agents/{id} and as the agent holds it (its sessions,
// what wakes it), and whether it comes back. It goes to the trash, restorable for 30 days, so the toast offers Undo.
// Afterwards the list reads again and you land on the next agent in it, else Home.
import { useEffect, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Trash2 } from 'lucide-react';
import { Agent, TrashItem, previewDelete, type NoClick } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { BUTTON_DANGER, BUTTON_GHOST } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { useWorkClient } from '../client';
import { useWorkNav } from '../nav';
import { useWorkPlace } from '../place';
import { AGENTS_KEY, STATES_KEY } from './reads';

/** What deleting an agent takes with it: the platform's own words, whether it comes back and how, and what it held. */
export interface AgentDeletion {
    deletes: string;
    reversible: boolean;
    undo: string | null;
    conversations: number;
    triggers: number;
}

export async function previewAgentDeletion(client: NoClick, agentId: string): Promise<AgentDeletion> {
    const agent = Agent.fromId(agentId, { client });
    const [preview, conversations, triggers] = await Promise.all([
        previewDelete('DELETE', `/v1/agents/${agentId}`, { client }),
        agent.conversations(),
        agent.triggers(),
    ]);
    return { deletes: preview.impact.deletes, reversible: preview.impact.reversible, undo: preview.impact.undo, conversations: conversations.length, triggers: triggers.filter((t) => t.kind !== 'channel' && t.kind !== 'routine').length };
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Asks before deleting an agent (`ask`), then deletes it: `order` is the agents as the list shows them, so you land on
 *  the one after it (else the one before, else Home) when it was the one open. */
export function useDeleteAgent(order: readonly string[]): { ask: (agent: { id: string; name: string }) => void; dialog: ReactNode } {
    const [asking, setAsking] = useState<{ id: string; name: string } | null>(null);
    return {
        ask: setAsking,
        dialog: asking ? <DeleteAgentDialog key={asking.id} agent={asking} order={order} onClose={() => setAsking(null)} /> : null,
    };
}

function DeleteAgentDialog({ agent, order, onClose }: { agent: { id: string; name: string }; order: readonly string[]; onClose: () => void }) {
    const client = useWorkClient();
    const nav = useWorkNav();
    const [place] = useWorkPlace();
    const [impact, setImpact] = useState<AgentDeletion | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        let live = true;
        previewAgentDeletion(client, agent.id).then(
            (found) => live && setImpact(found),
            (error: unknown) => live && setFailed(error instanceof Error ? error.message : String(error))
        );
        return () => {
            live = false;
        };
    }, [client, agent.id]);

    const reread = () => {
        invalidateV1(AGENTS_KEY);
        invalidateV1(STATES_KEY);
    };
    const confirm = async () => {
        setBusy(true);
        let trashed: TrashItem;
        try {
            trashed = await Agent.fromId(agent.id, { client }).delete();
        } catch (error) {
            setFailed(error instanceof Error ? error.message : String(error));
            setBusy(false);
            return;
        }
        reread();
        onClose();
        // Where it was open (its conversation, or its profile beside one), you go on to the next agent.
        if (place.agent === agent.id) {
            const at = order.indexOf(agent.id);
            const rest = order.filter((id) => id !== agent.id);
            const next = rest[at] ?? rest[at - 1] ?? null;
            if (next) nav.openAgent(next);
            else nav.openHome();
        }
        toast(`${agent.name} is in the trash`, {
            description: impact?.undo ?? 'Restore it within 30 days.',
            action: { label: 'Undo', onClick: () => void trashed.restore().then(reread, (error: unknown) => toast('Couldn’t bring it back', { description: error instanceof Error ? error.message : String(error) })) },
        });
    };

    const held = impact ? [impact.conversations ? plural(impact.conversations, 'conversation') : null, impact.triggers ? plural(impact.triggers, 'trigger') : null].filter(Boolean) : [];
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            tone="danger"
            title={`Delete ${agent.name}?`}
            description={impact ? impact.deletes : failed ? undefined : 'Checking what goes with it…'}
            mark={<Trash2 className="h-5 w-5" strokeWidth={1.75} />}
            testId="delete-agent"
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" disabled={busy || !impact} onClick={() => void confirm()} className={BUTTON_DANGER}>
                        {impact?.reversible === false ? 'Delete for good' : 'Move to the trash'}
                    </button>
                </>
            }
        >
            <div className="flex flex-col gap-3 pb-1 text-[13.5px]">
                {held.length > 0 && (
                    <div>
                        <p className="mb-1 text-[12.5px] text-muted-foreground">Goes with it</p>
                        <p>{new Intl.ListFormat('en', { type: 'conjunction' }).format(held as string[])}</p>
                    </div>
                )}
                {impact && <p className="text-muted-foreground">{impact.reversible ? (impact.undo ?? 'You can bring it back from the trash.') : 'It can’t be undone.'}</p>}
                {failed && (
                    <p role="alert" className="text-[13px] text-red-600 dark:text-red-400">
                        {failed}
                    </p>
                )}
            </div>
        </ShellDialog>
    );
}

// A space's tool servers waiting on a sign-in: its agents moved from a laptop with them, but the laptop had signed in
// to them in a browser, so each is signed in to again here (Connect), as on the agent's profile.
import { Plug } from 'lucide-react';
import { useAgents } from '../../agents/reads';
import { ConnectSignIn, useBrowserSignIn, useMovesSignIns, type BrowserSignIn } from '../../moves/signIns';
import { Group } from './Overview';
import { Lead, List } from './parts';
import type { Pane } from './pane';

export function MovedSignIns({ pane }: { pane: Pane }) {
    const agents = pane.share.of('agents');
    const read = useAgents();
    // The moves that brought this space's agents: each agent's own stamp, and what they stamped on the connections and
    // secrets they carried (an agent a user reads comes without its own).
    const moveIds = [
        ...(read.data ?? []).filter((a) => agents.some((t) => t.ref === a.id)).flatMap((a) => (a.movedFrom ? [a.movedFrom.moveId] : [])),
        ...[...pane.share.of('connections'), ...pane.share.of('secrets')].flatMap((t) => (t.movedFrom?.moveId ? [t.movedFrom.moveId] : [])),
    ];
    const signIns = useMovesSignIns(moveIds);
    const waiting = (signIns.data ?? []).filter((s) => s.needsSignIn && agents.some((a) => a.ref === s.agentId));
    if (!waiting.length) return null;
    return (
        <div className="mb-6" data-testid="moved-sign-ins">
            <Group title="Needs sign-in" meta={waiting.length}>
                <List>
                    {waiting.map((s) => (
                        <SignInRow key={`${s.moveId}:${s.name}`} signIn={s} agent={agents.find((a) => a.ref === s.agentId)?.name ?? null} />
                    ))}
                </List>
            </Group>
        </div>
    );
}

function SignInRow({ signIn, agent }: { signIn: BrowserSignIn; agent: string | null }) {
    const state = useBrowserSignIn(signIn);
    return (
        <div className="flex items-center gap-3 px-4 py-3" data-testid={`sign-in-${signIn.name}`}>
            <Lead mark={<Plug className="h-4 w-4 text-foreground/70" strokeWidth={1.75} />} />
            <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-foreground">{signIn.name}</span>
                <span className="block truncate text-[12.5px] text-muted-foreground">{[`Moved from ${signIn.host ?? 'a computer'}`, agent && `for ${agent}`, 'needs sign-in'].filter(Boolean).join(' · ')}</span>
                {state.problem && <span className="block text-[12.5px] text-red-600 dark:text-red-400">{state.problem}</span>}
            </span>
            <ConnectSignIn state={state} />
        </div>
    );
}

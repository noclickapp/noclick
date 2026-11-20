// An agent's MCP servers in "What it can use", each as the platform says it stands (`agent.toolServers`, read for the
// conversation the panel opens from): its mark, its name and one line of state, a green dot when connected, red when
// it didn't, a hollow ring when it waits on a person; Connect or Reconnect on the row where a person's sign-in is what's
// missing (the server's connect link, opened in a tab inside the click) and Reconnect where its harness can connect it
// again in place; and its own page, opened from the row, with its host, how it signs in and each tool it offers.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ChevronRight } from 'lucide-react';
import { Agent, OperationTimeout, type AgentToolServer } from 'noclick';
import { openTabForLater } from '@/lib/oauthPopup';
import { errorText } from '@/screens/console/pages/resources/shared';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { agoText } from '../agents/states';
import { HarnessMark } from '../agents/harness';
import { AppMark, catalogApp } from '../newAgent/wakes';
import { ConnectSignIn } from '../moves/signIns';
import { ReconnectPill } from '../profile/toolServers';
import { rereadAgent } from '../profile/reads';

/** How long a sign-in in another tab is waited on before the row lets it go (the link itself lasts longer). */
const SIGN_IN_WAIT_S = 15 * 60;

const SIGN_IN: Record<AgentToolServer['signIn'], string> = { none: 'Open, no sign-in', key: 'Uses a key', browser: 'Browser sign-in' };

const toolCount = (n: number) => `${n} ${n === 1 ? 'tool' : 'tools'}`;

/** What a server's line says: its state in words, and the dot that goes with them. */
export function serverWords(s: AgentToolServer, now = Date.now()): { text: string; tone: 'live' | 'fail' | 'wait' | 'busy' | null } {
    switch (s.status) {
        case 'connected':
            return { text: ['Connected', s.tools.length ? toolCount(s.tools.length) : null].filter(Boolean).join(' · '), tone: 'live' };
        case 'connecting':
            return { text: 'Connecting…', tone: 'busy' };
        case 'needs_sign_in':
            return { text: s.signIn === 'key' ? 'Needs its key' : 'Needs sign-in', tone: 'wait' };
        case 'signed_out': {
            const reason = s.problem?.reason;
            if (reason === 'refused') return { text: 'Its key was refused', tone: 'wait' };
            if (reason === 'revoked') return { text: 'Its sign-in was revoked', tone: 'wait' };
            return { text: ['Sign-in ended', s.problem?.since ? agoText(now - s.problem.since.getTime()) : null].filter(Boolean).join(' '), tone: 'wait' };
        }
        case 'failed':
            return { text: `Didn’t connect: ${s.problem?.providerSaid ?? s.problem?.message ?? 'no tools came back'}`, tone: 'fail' };
        default:
            return { text: 'Connects on its next turn', tone: null };
    }
}

function Dot({ tone, className }: { tone: ReturnType<typeof serverWords>['tone']; className?: string }) {
    if (!tone) return null;
    return (
        <span
            aria-hidden
            className={cn(
                'mt-[4.5px] h-[7px] w-[7px] shrink-0 rounded-full',
                tone === 'live' && 'bg-emerald-500',
                tone === 'fail' && 'bg-red-500',
                tone === 'wait' && 'shadow-[inset_0_0_0_1.5px_hsl(var(--muted-foreground))]',
                tone === 'busy' && 'animate-pulse bg-foreground/35 motion-reduce:animate-none',
                className
            )}
        />
    );
}

/** What draws a server: its app's logo, NoClick's mark for NoClick's own, else its name's first letter. */
export function ServerMark({ server }: { server: AgentToolServer }) {
    const icon = server.icon;
    const inner: ReactNode =
        icon && 'mark' in icon ? (
            <HarnessMark harness="sdk" className="h-3.5 w-3.5" />
        ) : icon ? (
            <AppMark nodeType={catalogApp(icon.integration).nodeType} className="h-4 w-4" />
        ) : (
            <span className="text-[12px] font-semibold uppercase text-foreground/75">{server.name.slice(0, 1)}</span>
        );
    return <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/75 ring-1 ring-inset ring-foreground/[0.05]">{inner}</span>;
}

type Busy = 'signing' | 'retrying' | null;

/** Signing a person in to a server through its connect link, in a tab opened inside the click, and connecting a server
 *  its conversation's harness can connect again in place. Each reads the agent's servers again once it's done. */
export function useServerActions(agentId: string, conversation: string | null) {
    const client = useWorkClient();
    const [busy, setBusy] = useState<Record<string, Busy>>({});
    const live = useRef(true);
    useEffect(
        () => () => {
            live.current = false;
        },
        []
    );
    const set = (id: string, to: Busy) => live.current && setBusy((now) => ({ ...now, [id]: to }));

    const signIn = (server: AgentToolServer, onSignedIn?: () => void) => {
        const tab = openTabForLater();
        set(server.id, 'signing');
        void (async () => {
            try {
                const link = await server.connectLink();
                // A browser that refused the window opens it from the toast's own click.
                if (!tab.go(link.url)) toast(`Your browser didn’t open the sign-in to ${server.name}`, { action: { label: 'Open it', onClick: () => openTabForLater({ url: link.url }) } });
                await link.wait({ timeoutS: SIGN_IN_WAIT_S });
                onSignedIn?.();
            } catch (error) {
                tab.close();
                if (!(error instanceof OperationTimeout)) toast(`Couldn’t sign in to ${server.name}`, { description: errorText(error) });
            } finally {
                set(server.id, null);
                rereadAgent(agentId);
            }
        })();
    };

    const reconnect = async (server: AgentToolServer) => {
        set(server.id, 'retrying');
        try {
            await Agent.fromId(agentId, { client }).conversation(conversation!).reconnectToolServer(server.name);
        } catch (error) {
            toast(`Couldn’t reconnect ${server.name}`, { description: errorText(error) });
        } finally {
            set(server.id, null);
            rereadAgent(agentId);
        }
    };
    return { busy, signIn, reconnect };
}

/** The one thing a server's row offers, where there is one: a sign-in, the first or again, or a reconnect in place. */
function ServerAction({ server, busy, actions }: { server: AgentToolServer; busy: Busy; actions: ReturnType<typeof useServerActions> }) {
    const signsIn = server.signIn === 'browser' && (server.status === 'needs_sign_in' || server.status === 'signed_out');
    if (signsIn || busy === 'signing')
        return <ConnectSignIn label={server.status === 'signed_out' ? 'Reconnect' : 'Connect'} state={{ ready: !busy, connecting: busy === 'signing', connect: () => actions.signIn(server) }} />;
    if (server.reconnectable || busy === 'retrying') return <ReconnectPill busy={busy === 'retrying'} disabled={!!busy} onClick={() => void actions.reconnect(server)} />;
    return null;
}

/** Its line while a sign-in or a reconnect runs, else its state. */
function lineOf(server: AgentToolServer, busy: Busy) {
    if (busy === 'signing') return { text: `Sign in to ${server.host ?? server.name} in the window that opened`, tone: null };
    if (busy === 'retrying') return { text: `Connecting to ${server.host ?? server.name} again`, tone: null };
    return serverWords(server);
}

export function ServerRow({ server, actions, onOpen, remove }: { server: AgentToolServer; actions: ReturnType<typeof useServerActions>; onOpen: () => void; remove: ReactNode }) {
    const busy = actions.busy[server.id] ?? null;
    const line = lineOf(server, busy);
    return (
        <div className="group flex min-h-11 w-full items-center gap-1.5 rounded-[16px] py-1.5 pl-2 pr-1" data-tool={`server:${server.id}`} data-status={server.status}>
            <button type="button" onClick={onOpen} aria-label={`${server.name}: ${line.text}`} className="-my-1 -ml-2 mr-0 flex min-w-0 flex-1 items-center gap-3 rounded-[14px] py-1 pl-2 pr-1.5 text-left transition-colors hover:bg-foreground/[0.04]">
                <ServerMark server={server} />
                <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1 text-[13.5px] font-medium leading-5">
                        <span className="truncate">{server.name}</span>
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                    </span>
                    <span className={cn('flex min-w-0 items-start gap-1.5 text-[12px] leading-4', line.tone === 'fail' ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                        <Dot tone={line.tone} />
                        <span className="line-clamp-2 min-w-0">{line.text}</span>
                    </span>
                </span>
            </button>
            <ServerAction server={server} busy={busy} actions={actions} />
            {remove}
        </div>
    );
}

/** When the newest failure among the servers was found, for the section's heading (" · checked 4m ago"). */
export function checkedLine(servers: readonly AgentToolServer[], now = Date.now()): string | null {
    const newest = Math.max(...servers.filter((s) => s.status === 'failed' && s.checkedAt).map((s) => s.checkedAt!.getTime()));
    return Number.isFinite(newest) ? ` · checked ${agoText(now - newest)}` : null;
}

/** A server's own page: its state, host and sign-in, then each tool it offers with what it does. */
export function ServerPage({ server, actions, onRemove }: { server: AgentToolServer; actions: ReturnType<typeof useServerActions>; onRemove: () => void }) {
    const busy = actions.busy[server.id] ?? null;
    const line = lineOf(server, busy);
    const missing = server.status === 'needs_sign_in' ? (server.signIn === 'key' ? 'Its tools show once it has its key.' : 'Its tools show once you sign in.') : server.status === 'unchecked' ? 'Its tools show after its next turn.' : null;
    return (
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 scrollbar-subtle" data-testid="tool-server-page">
            <div className="flex items-center gap-2.5 px-2 pb-2 pt-1">
                <ServerMark server={server} />
                <span className={cn('flex min-w-0 flex-1 items-start gap-1.5 text-[12px] leading-4', line.tone === 'fail' ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                    <Dot tone={line.tone} />
                    <span className="min-w-0">{[line.text, server.host, SIGN_IN[server.signIn]].filter(Boolean).join(' · ')}</span>
                </span>
                <ServerAction server={server} busy={busy} actions={actions} />
            </div>
            {server.tools.length > 0 && (
                <ul aria-label={`${server.name}’s tools`}>
                    {server.tools.map((tool) => (
                        <li key={tool.name} className="flex flex-col rounded-[14px] px-2 py-1.5">
                            <span className="font-mono text-[12px] leading-[18px] text-foreground">{tool.name}</span>
                            {tool.description && <span className="text-[12px] leading-4 text-muted-foreground">{tool.description}</span>}
                        </li>
                    ))}
                </ul>
            )}
            {missing && <p className="px-2 py-1 text-[12px] leading-4 text-muted-foreground">{missing}</p>}
            {server.status === 'signed_out' && server.tools.length > 0 && <p className="px-2 py-1 text-[12px] leading-4 text-muted-foreground">From before its sign-in ended.</p>}
            <button type="button" onClick={onRemove} className="mx-2 mt-2 text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground">
                Take {server.name} away
            </button>
        </div>
    );
}

// Clear and resume, the two things a person does to an agent's one session, as every page offers them (Work's session
// menu and box, the Chat page's box and "+" menu, the profile's Sessions line): clearing starts the agent fresh for
// everyone talking to it, resuming switches everyone back to an earlier session; each confirms first, its files never
// change, and neither runs while a turn does (the platform refuses one then too). The pages showing the agent move to
// the new session on its `session` frame (sessions.ts).
import { useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Check, MessageCircle, RotateCcw, SquarePen } from 'lucide-react';
import { invalidateV1 } from '@/sdk/useV1';
import type { ComposerSessionActions } from '@/ui/chat/ComposerAddMenu';
import { Conflict, type Agent, type Conversation } from 'noclick';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { sessionsKey, useSessions, type Sessions } from './sessions';
import { dayOf } from './Timeline';

/** What a menu says beside clear or resume while a turn runs. */
export const STOP_FIRST = 'Stop it first';

/** A session as its row names it: its title or first words. */
export const sessionLabel = (c: Conversation) => c.title ?? c.preview ?? (c.active ? 'This session' : 'An empty session');

export interface SessionControls {
    sessions: Sessions | null;
    /** Earlier sessions it can resume, most recent first. */
    earlier: Conversation[];
    working: boolean;
    /** Opens the confirm for a clear (or says to stop it first). */
    clear(): void;
    /** Opens the list of sessions to resume. */
    resume(): void;
    /** Opens the confirm for resuming `session`. */
    pick(session: Conversation): void;
    /** Both as the box's "+" menu offers them. */
    menu: ComposerSessionActions;
    dialogs: ReactNode;
}

type Open = { kind: 'clear' } | { kind: 'list' } | { kind: 'confirm'; session: Conversation } | null;

/** Clear and resume for `agent` (`agentId` once known), named `name`, which is `working` on a turn or not. */
export function useSessionControls(agent: Agent, agentId: string | null, name: string, working: boolean): SessionControls {
    const { sessions } = useSessions(agentId);
    const [open, setOpen] = useState<Open>(null);
    const [busy, setBusy] = useState(false);
    const earlier = (sessions?.all ?? []).filter((c) => !c.active && c.conversation !== sessions?.active && !c.archived);
    const stopFirst = () => toast(STOP_FIRST, { description: `${name} is working on a turn. Stop it, then try again.` });
    const guarded = (next: Open) => (working ? stopFirst() : setOpen(next));

    const run = async (move: () => Promise<unknown>, failed: string) => {
        setBusy(true);
        try {
            await move();
            setOpen(null);
            if (agentId) invalidateV1(sessionsKey(agentId));
        } catch (e) {
            if (e instanceof Conflict) stopFirst();
            else toast(failed, { description: e instanceof Error ? e.message : String(e) });
        } finally {
            setBusy(false);
        }
    };

    const close = (o: boolean) => !o && !busy && setOpen(null);
    const dialogs =
        open?.kind === 'clear' ? (
            <ShellDialog
                open
                onOpenChange={close}
                title={`Start ${name} fresh for everyone?`}
                description="Every chat, group and channel it’s in, your messages, its triggers and anyone on its shared link continue in a new session. Its files stay. This session is kept under Earlier sessions."
                mark={<SquarePen className="h-5 w-5" strokeWidth={2} />}
                footer={
                    <>
                        <button type="button" onClick={() => setOpen(null)} className={BUTTON_GHOST}>
                            Cancel
                        </button>
                        <button type="button" disabled={busy} onClick={() => void run(() => agent.clear(), 'It didn’t start a new session')} className={BUTTON_PRIMARY}>
                            Clear for everyone
                        </button>
                    </>
                }
            />
        ) : open?.kind === 'list' ? (
            <ShellDialog open onOpenChange={close} title="Resume an earlier session" description={`Everyone talking to ${name} continues there. Its files don’t change.`} mark={<RotateCcw className="h-5 w-5" strokeWidth={2} />} size="md">
                <SessionRows sessions={sessions?.all ?? []} active={sessions?.active ?? null} onPick={(session) => guarded({ kind: 'confirm', session })} />
            </ShellDialog>
        ) : open?.kind === 'confirm' ? (
            <ShellDialog
                open
                onOpenChange={close}
                title={`Switch ${name} back to this session for everyone talking to it?`}
                description="Its files don’t change."
                mark={<RotateCcw className="h-5 w-5" strokeWidth={2} />}
                footer={
                    <>
                        <button type="button" onClick={() => setOpen(null)} className={BUTTON_GHOST}>
                            Cancel
                        </button>
                        <button type="button" disabled={busy} onClick={() => void run(() => agent.conversation(open.session.conversation).resume(), 'It didn’t switch sessions')} className={BUTTON_PRIMARY}>
                            Switch back
                        </button>
                    </>
                }
            >
                <p className="truncate rounded-full bg-foreground/[0.04] px-4 py-2 text-muted-foreground">
                    {sessionLabel(open.session)}
                    {open.session.lastActivity && <span className="opacity-70"> · until {dayOf(open.session.lastActivity.getTime())}</span>}
                </p>
            </ShellDialog>
        ) : null;

    const clear = () => guarded({ kind: 'clear' });
    const resume = () => guarded({ kind: 'list' });
    return {
        sessions,
        earlier,
        working,
        clear,
        resume,
        pick: (session) => guarded({ kind: 'confirm', session }),
        menu: { onClear: clear, onResume: resume, blocked: working ? STOP_FIRST : null },
        dialogs,
    };
}

/** Its sessions as rows to pick from: each by its first words and when it was last active, the one it's in checked. */
export function SessionRows({ sessions, active, onPick, className }: { sessions: readonly Conversation[]; active: string | null; onPick: (session: Conversation) => void; className?: string }) {
    const shown = sessions.filter((c) => !c.archived);
    if (!shown.length) return <p className="py-2 text-muted-foreground">No earlier sessions yet.</p>;
    return (
        <ul className={cn('-mx-2 space-y-0.5', className)}>
            {shown.map((c) => {
                const current = c.conversation === active;
                return (
                    <li key={c.conversation}>
                        <button
                            type="button"
                            disabled={current}
                            onClick={() => onPick(c)}
                            aria-current={current || undefined}
                            className="flex w-full min-w-0 items-center gap-2.5 rounded-full px-3 py-2 text-left transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 disabled:hover:bg-transparent"
                        >
                            <MessageCircle className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                            <span className="min-w-0 flex-1 truncate">{sessionLabel(c)}</span>
                            {c.lastActivity && <span className="shrink-0 text-xs text-muted-foreground">{dayOf(c.lastActivity.getTime())}</span>}
                            {current && <Check className="h-3.5 w-3.5 shrink-0" strokeWidth={2.25} aria-label="The session it’s in" />}
                        </button>
                    </li>
                );
            })}
        </ul>
    );
}

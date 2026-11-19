// A helper beside the Chat page: Work's own AgentConversation for the agent NoClick handed work to, in its one session
// (a child's task, an app coding agent's own), so its work reads as Work's activity log and a message to it goes where
// Work's would. `?watch=<agent id>` keeps it open across a reload. On a laptop it is a column beside the chat, dragged
// wider from its left edge; on a phone a sheet over the page, pulled down (or ⌄) to go back. Opening its profile or
// machine goes to Work.
import { useCallback, useMemo, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'react-router';
import * as Dialog from '@radix-ui/react-dialog';
import { AgentConversation } from '@/screens/work/conversation/AgentConversation';
import { useActiveSession } from '@/screens/work/conversation/sessions';
import { WorkNavContext, type WorkNav } from '@/screens/work/nav';
import { WorkViewerContext, type WorkViewer } from '@/screens/work/viewer';
import { createPanelWidth } from '@/ui/panelWidth';
import { ResizeEdge } from '@/ui/ResizeEdge';
import { standing } from '@/slots';
import { withPlace, type PlaceChange } from '@/screens/work/place';
import { WORK_ADDRESS } from '@/screens/work/slots';
import { cn } from '@/ui/utils';
import type { Helper } from './model';

export const WATCH_PARAM = 'watch';

/** The helper open beside the chat (`?watch=`), and how to open one or close it. */
export function useWatching(): [Helper | null, (helper: Helper | null) => void] {
    const [params, setParams] = useSearchParams();
    const raw = params.get(WATCH_PARAM);
    const watching = useMemo<Helper | null>(() => (raw ? { agentId: raw } : null), [raw]);
    const watch = useCallback(
        (helper: Helper | null) =>
            setParams(
                (prev) => {
                    const next = new URLSearchParams(prev);
                    if (helper) next.set(WATCH_PARAM, helper.agentId);
                    else next.delete(WATCH_PARAM);
                    return next;
                },
                { preventScrollReset: true }
            ),
        [setParams]
    );
    return [watching, watch];
}

/** The account looking at its own agents, as the Chat page always is. */
const ACCOUNT: WorkViewer = { type: 'account', id: null, name: null };

/** Work, where its host says it is, at `change`. */
const work = (change: PlaceChange) => standing(WORK_ADDRESS).go(withPlace(new URLSearchParams(), change));

/** Where the helper's links go from the Chat page: another helper opens here, anything else in Work. */
function chatNav(watch: (helper: Helper) => void): WorkNav {
    return {
        openChannel: (channel, options) => work({ view: 'home', channel, thread: options?.thread ?? null }),
        openDm: () => work({ view: 'dms' }),
        openAgent: (agentId) => watch({ agentId }),
        openProfile: (agentId, at) => work({ view: 'agents', agent: agentId, panel: 'profile', profileTab: at?.tab ?? null, trigger: at?.trigger ?? null }),
        openMachine: (agentId) => work({ view: 'agents', agent: agentId, machine: true }),
        newAgent: () => work({ view: 'agents', agent: 'new' }),
        openHome: () => work({ view: 'home' }),
        openMembers: (tab) => work({ panel: tab ?? 'people' }),
        closePanel: () => undefined,
    };
}

function Conversation({ helper, watch, onClose }: { helper: Helper; watch: (helper: Helper) => void; onClose: () => void }) {
    const nav = useMemo(() => chatNav(watch), [watch]);
    const session = useActiveSession(helper.agentId);
    const open = (to: PlaceChange) => work({ view: 'agents', agent: helper.agentId, ...to });
    return (
        <WorkViewerContext.Provider value={ACCOUNT}>
            <WorkNavContext.Provider value={nav}>
                {session && <AgentConversation key={`${helper.agentId}:${session}`} agentId={helper.agentId} conversation={session} onOpenProfile={() => open({ panel: 'profile' })} onOpenMachine={() => open({ machine: true })} onClose={onClose} />}
            </WorkNavContext.Provider>
        </WorkViewerContext.Provider>
    );
}

const HELPER_COLUMN = createPanelWidth({ key: 'nc-watch-column', initial: 560, min: 400, max: 880 });

function Column({ children }: { children: ReactNode }) {
    const width = HELPER_COLUMN.useWidth();
    const resizing = HELPER_COLUMN.useResizing();
    return (
        <aside
            style={{ width }}
            className={cn('relative flex h-full max-w-full flex-col border-l border-border bg-background dark:border-foreground/[0.08]', resizing && 'select-none')}
            aria-label="A helper at work"
            data-testid="helper-column"
        >
            <ResizeEdge panel={HELPER_COLUMN} side="left" label="Resize the column" />
            {children}
        </aside>
    );
}

/** How far a pull down goes before letting go closes the sheet. */
const PULL_CLOSES = 110;

function Sheet({ onClose, children }: { onClose: () => void; children: ReactNode }) {
    const [pull, setPull] = useState(0);
    const onPull = (e: ReactPointerEvent<HTMLElement>) => {
        const startY = e.clientY;
        const el = e.currentTarget;
        el.setPointerCapture(e.pointerId);
        const move = (ev: PointerEvent) => setPull(Math.max(0, ev.clientY - startY));
        const up = (ev: PointerEvent) => {
            el.removeEventListener('pointermove', move);
            el.removeEventListener('pointerup', up);
            el.removeEventListener('pointercancel', up);
            if (ev.clientY - startY > PULL_CLOSES) onClose();
            setPull(0);
        };
        el.addEventListener('pointermove', move);
        el.addEventListener('pointerup', up);
        el.addEventListener('pointercancel', up);
    };
    return (
        <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
            <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-[60] bg-black/30 data-[state=open]:animate-in data-[state=open]:fade-in-0 dark:bg-black/60" />
                <Dialog.Content
                    // Nothing takes focus as it opens: a phone raises no keyboard.
                    onOpenAutoFocus={(e) => e.preventDefault()}
                    style={{ transform: pull ? `translateY(${pull}px)` : undefined, transition: pull ? 'none' : undefined }}
                    className="fixed inset-x-0 bottom-0 top-3 z-[70] flex flex-col overflow-hidden rounded-t-[26px] bg-background pb-[max(env(safe-area-inset-bottom),10px)] outline-none ring-1 ring-inset ring-border transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom motion-reduce:transition-none dark:ring-foreground/[0.09]"
                    data-testid="helper-sheet"
                >
                    <Dialog.Title className="sr-only">A helper at work</Dialog.Title>
                    <Dialog.Description className="sr-only">What the agent NoClick handed work to is doing.</Dialog.Description>
                    <button type="button" aria-label="Back to the chat" onPointerDown={onPull} onClick={onClose} className="group/grab flex h-5 w-full shrink-0 touch-none items-center justify-center focus-visible:outline-none">
                        <span className="h-1 w-9 rounded-full bg-foreground/15 transition-colors group-hover/grab:bg-foreground/30 group-focus-visible/grab:bg-ring" />
                    </button>
                    <div className="flex min-h-0 flex-1 flex-col">{children}</div>
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
    );
}

/** The helper's session: a column in `aside` (beside the chat) on a laptop, a sheet on a phone. */
export function HelperColumn({ helper, aside, phone, watch, onClose }: { helper: Helper; aside: HTMLElement | null; phone: boolean; watch: (helper: Helper) => void; onClose: () => void }) {
    const body = <Conversation helper={helper} watch={watch} onClose={onClose} />;
    if (phone) return <Sheet onClose={onClose}>{body}</Sheet>;
    return aside ? createPortal(<Column>{body}</Column>, aside) : null;
}

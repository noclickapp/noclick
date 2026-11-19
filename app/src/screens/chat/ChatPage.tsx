// The Chat page: the conversation with the account's NoClick, drawn over whichever chat it's given (`ChatSource`: its
// own transcript and its own box). Empty, it asks what to take care of in the landing page's
// voice, with a few quiet starts; once there is a thread, it is the thread, with the box pinned below. Until the page
// knows which (a device opening the chat for the first time), it shows neither. Connect (top left) lists the other ways
// into the conversation. The first message carries the box from the middle of the page to its place under the thread.
// Arriving from an agent page (where its host has them), the thread opens on that agent being set up.
import { useCallback, useContext, useEffect, useState } from 'react';
import { flushSync } from 'react-dom';
import { ArrowUpRight, Brain } from 'lucide-react';
import type { ChatReference } from '@/lib/agentThread/messages';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { useStickToBottom } from '@/ui/chat/useStickToBottom';
import { consumePendingAsk, onAskNoClick } from './asks';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { Status } from '@/ui/chat/primitives';
import { PhoneBarActions, useInPhoneShell } from '@/ui/phoneBar';
import { NodeMark } from '@/ui/primitives';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { SidePanel } from '@/ui/SidePanel';
import { Skeleton } from '@/ui/skeleton';
import { DISPLAY } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { ConnectMenu } from './connect/ConnectMenu';
import { useChatContext, type ChatArrival } from './context';
import { CoordinatorMemories } from './memories/CoordinatorMemories';
import { useChatSource } from './source';

/** Nothing arrives where the host finishes no setups here. */
const noArrival = (): ChatArrival => ({ arriving: null });

// Starts, each marked by the app it centres on.
const STARTERS: { title: string; detail: string; mark: string; prompt: string }[] = [
    {
        title: 'Brief me every morning',
        detail: 'Your inbox, calendar and last night’s runs, on WhatsApp at 8.',
        mark: 'automation-whatsapp',
        prompt: 'Every morning at 8, send me a WhatsApp brief: new emails that need me, today’s calendar, and what my automations did overnight.',
    },
    {
        title: 'Answer my support inbox',
        detail: 'Routine replies go out; the hard ones come to you in Slack.',
        mark: 'automation-gmail',
        prompt: 'Build an agent that answers my support inbox and hands the hard ones to me in Slack.',
    },
    {
        title: 'Give my agents a number',
        detail: 'A phone number they answer calls and texts on, day and night.',
        mark: 'automation-phone',
        prompt: 'Get a phone number my agents can answer calls and texts on.',
    },
];

function StarterCard({ title, detail, mark, disabled, onTry, className }: { title: string; detail: string; mark: string; disabled: boolean; onTry: () => void; className?: string }) {
    return (
        <button
            type="button"
            disabled={disabled}
            onClick={onTry}
            className={cn(
                'group flex min-h-[116px] flex-col rounded-2xl p-3.5 text-left ring-1 ring-inset ring-border/70 transition-colors hover:bg-foreground/[0.025] hover:ring-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 dark:ring-foreground/[0.06] dark:hover:bg-foreground/[0.03] dark:hover:ring-foreground/[0.1]',
                className
            )}
        >
            <span className="flex w-full items-center">
                <span className="grid h-7 w-7 place-items-center rounded-lg bg-foreground/[0.05]">
                    <NodeMark type={mark} size="sm" />
                </span>
                <ArrowUpRight className="ml-auto h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
            </span>
            <span className="mt-auto pt-4 text-[13.5px] font-medium text-foreground/90">{title}</span>
            <span className="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-muted-foreground">{detail}</span>
        </button>
    );
}

/** The view-transition name the box carries from the middle of an empty page to the thread's foot. */
export const COMPOSER_TRANSITION = 'nc-composer';

// On the page's own background, so the thread scrolling under it never shows through; it answers taps a fingertip wide.
const ICON_BUTTON =
    "relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-background after:absolute after:-inset-1 after:rounded-full after:content-[''] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40";

/** The thread's outline, shown only if loading it takes long enough to notice. */
export function ThreadLoading() {
    const [shown, setShown] = useState(false);
    useEffect(() => {
        const timer = setTimeout(() => setShown(true), 300);
        return () => clearTimeout(timer);
    }, []);
    return (
        <div role="status" className="flex h-full flex-col justify-end" data-testid="coordinator-loading">
            <span className="sr-only">Loading your conversation</span>
            <div aria-hidden className={cn('mx-auto w-full max-w-3xl space-y-8 px-5 pb-28 transition-opacity duration-500 sm:px-6', shown ? 'opacity-100' : 'opacity-0')}>
                <Skeleton className="ml-auto h-10 w-56 rounded-3xl" />
                <div className="space-y-2.5">
                    <Skeleton className="h-3.5 w-11/12" />
                    <Skeleton className="h-3.5 w-4/5" />
                    <Skeleton className="h-3.5 w-2/5" />
                </div>
                <Skeleton className="ml-auto h-10 w-40 rounded-3xl" />
                <div className="space-y-2.5">
                    <Skeleton className="h-3.5 w-3/4" />
                    <Skeleton className="h-3.5 w-1/2" />
                </div>
            </div>
        </div>
    );
}

type StartViewTransition = (update: () => void) => unknown;

/** Run a state change inside a view transition where the browser has them and
 *  the user hasn't asked for less motion; otherwise just run it. */
function withViewTransition(update: () => void) {
    const start = (document as Document & { startViewTransition?: StartViewTransition }).startViewTransition;
    if (!start || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        update();
        return;
    }
    start.call(document, () => flushSync(update));
}

/** An element's width as it changes; 0 until it's laid out. */
function useWidthOf(el: HTMLElement | null): number {
    const [width, setWidth] = useState(0);
    useEffect(() => {
        if (!el) return;
        setWidth(el.getBoundingClientRect().width);
        if (typeof ResizeObserver === 'undefined') return;
        const watch = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
        watch.observe(el);
        return () => watch.disconnect();
    }, [el]);
    return width;
}

/** The page over the chat whose provider it's drawn in. */
export function ChatPage() {
    const coordinator = useChatSource();
    const useArrival = useChatContext().useArrival ?? noArrival;
    // Who reads the memories: the owner, or everyone who signs in to an app acting as one of the account's keys.
    const asKey = useContext(ConsoleContext)?.actsAs === 'key';
    const { isStreaming, conversationId, send, loaded, Beside, Composer } = coordinator;
    const inPhone = useInPhoneShell();
    // Words put in the box from elsewhere (it keeps what's typed itself).
    const [putBack, setPutBack] = useState<{ text: string; references?: ChatReference[]; n: number } | null>(null);
    const [memoriesOpen, setMemoriesOpen] = useState(false);
    // Beside the thread, where the Beside opens a helper's conversation on a laptop.
    const [aside, setAside] = useState<HTMLDivElement | null>(null);
    // The chat column, which the Beside floats over, and the room on its right the thread and composer give it.
    const [column, setColumn] = useState<HTMLDivElement | null>(null);
    const width = useWidthOf(column);
    const [reserve, setReserve] = useState(0);
    const arrival = useArrival(conversationId, coordinator.arrive);
    const { arriving } = arrival;
    // Until its note is in the thread, the agent being set up holds the thread open.
    const thread = coordinator.thread;
    const size = thread.size;
    const settingUp = !!arriving && !thread.setups.includes(arriving.workflowId ?? '');
    const view = settingUp || size > 0 ? 'thread' : loaded ? 'start' : 'loading';
    const empty = view === 'start';
    // Pinned to the newest message unless the reader scrolled up, including while a card that loads after its message
    // (a canvas, a list of numbers) grows the thread.
    const scroller = useStickToBottom([thread.moved, isStreaming]);

    // A start goes on its own, never with what the box holds.
    const start = useCallback(
        (text: string) => {
            const go = () => void send(text, [], []);
            // The first message moves the composer from the middle of the page to the foot of the thread.
            if (empty) withViewTransition(go);
            else go();
        },
        [send, empty]
    );

    const draftAndFocus = useCallback((text: string, pointsAt?: ChatReference[]) => {
        setPutBack((p) => ({ text, references: pointsAt, n: (p?.n ?? 0) + 1 }));
    }, []);

    // "Ask NoClick" from another page (or a card) lands here as a draft, with what it points at.
    useEffect(() => {
        const take = () => {
            const ask = consumePendingAsk();
            if (!ask) return;
            draftAndFocus(ask.text, ask.references);
        };
        take();
        return onAskNoClick(take);
    }, [draftAndFocus]);

    if (coordinator.gated) {
        return (
            <div className="flex h-full items-center justify-center px-6">
                <p className="max-w-sm text-center text-[14px] text-muted-foreground">Chat with NoClick isn’t available on this account yet.</p>
            </div>
        );
    }

    if (view === 'loading') {
        if (coordinator.loadError) {
            return (
                <div className="flex h-full flex-col items-center justify-center gap-4 px-6" data-testid="coordinator-load-error">
                    <p className="max-w-sm text-center text-[14px] text-muted-foreground">Your conversation didn’t load.</p>
                    <button type="button" className={BUTTON_SECONDARY} onClick={coordinator.retry}>
                        Try again
                    </button>
                </div>
            );
        }
        return <ThreadLoading />;
    }

    const composer = (
        <Composer
            placeholder={empty ? 'Describe a task, or ask anything' : 'Message NoClick'}
            size={empty ? 'tall' : 'default'}
            putBack={putBack}
            transition={(update) => {
                // Sent, the words put in it are gone: the box drawn at the thread's foot opens empty.
                setPutBack(null);
                if (empty) withViewTransition(update);
                else update();
            }}
            transitionName={COMPOSER_TRANSITION}
            className={empty && !inPhone ? 'px-0 pb-0 pt-0 sm:px-0' : undefined}
        />
    );
    const beside = Beside && <Beside draft={draftAndFocus} aside={aside} width={width} onReserve={setReserve} />;
    const reserved = reserve ? { paddingRight: reserve } : undefined;

    const memories = (
        <>
            <SidePanel
                open={memoriesOpen}
                onOpenChange={setMemoriesOpen}
                title="Memories"
                description={asKey ? 'What NoClick remembers. Everyone who can sign in to this app sees them.' : 'What NoClick remembers. Only you can see them.'}
            >
                <CoordinatorMemories transport={coordinator.memories} />
            </SidePanel>
            {arrival.aside}
        </>
    );
    const memoriesButton = (
        <ShortcutTooltip label="Memories">
            <button type="button" className={ICON_BUTTON} aria-label="Memories" onClick={() => setMemoriesOpen(true)}>
                <Brain className="h-4 w-4" />
            </button>
        </ShortcutTooltip>
    );
    // The page's corners on a laptop; a phone puts both in its bar.
    const corners = inPhone ? (
        <PhoneBarActions>
            <ConnectMenu align="end" onAsk={draftAndFocus} />
            {memoriesButton}
        </PhoneBarActions>
    ) : (
        <>
            <div className="absolute left-4 top-3 z-10">
                <ConnectMenu onAsk={draftAndFocus} />
            </div>
            <div className="absolute right-4 top-3 z-10">{memoriesButton}</div>
        </>
    );

    if (empty) {
        const headline = (
            <div className={cn(DISPLAY, 'text-balance leading-[1.02]')}>
                <h1 className="text-foreground">What should I take care of?</h1>
            </div>
        );
        const starters = (className?: string) =>
            STARTERS.map(({ title, detail, mark, prompt }) => (
                <StarterCard key={title} title={title} detail={detail} mark={mark} disabled={!conversationId} onTry={() => start(prompt)} className={className} />
            ));

        // A phone keeps the composer where the thumb is, as the thread does.
        if (inPhone) {
            return (
                <div className="flex h-full flex-col" data-testid="coordinator-home">
                    {corners}
                    {beside}
                    <div className="flex min-h-0 flex-1 flex-col justify-center px-6 text-[36px]">{headline}</div>
                    <div className="flex snap-x gap-2.5 overflow-x-auto scroll-px-4 px-4 pb-3 scrollbar-hide">{starters('w-[228px] shrink-0 snap-start')}</div>
                    {composer}
                    {memories}
                </div>
            );
        }

        return (
            <div ref={setColumn} className="relative flex h-full flex-col" data-testid="coordinator-home">
                {corners}
                {beside}
                <div className="relative min-h-0 flex-1 overflow-y-auto scrollbar-subtle" style={reserved}>
                    <div className="mx-auto flex min-h-full w-full max-w-[760px] flex-col justify-center px-8 pb-[12vh] pt-16">
                        <div className="text-[54px] xl:text-[60px]">{headline}</div>
                        <div className="mt-9">{composer}</div>
                        <div className="mt-4 grid grid-cols-3 gap-2.5">{starters()}</div>
                    </div>
                </div>
                {memories}
            </div>
        );
    }

    return (
        <div className="flex h-full min-h-0">
            <div ref={setColumn} className="relative flex h-full min-w-0 flex-1 flex-col" data-testid="coordinator-home">
                {corners}
                {beside}
                <div ref={scroller.ref} onScroll={scroller.onScroll} className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle" style={reserved}>
                    <div className={cn('mx-auto w-full max-w-3xl px-5 pb-10 sm:px-6', inPhone ? 'pt-4' : 'pt-14')}>
                        <thread.Transcript />
                        {settingUp && (
                            <div className={size ? 'mt-6' : undefined}>
                                <Status state="working">Setting up {arriving.name}</Status>
                            </div>
                        )}
                    </div>
                </div>
                <div className="shrink-0" style={reserved}>
                    {composer}
                </div>
                {memories}
            </div>
            {/* What opens beside the thread keeps the thread at least this wide. */}
            <div ref={setAside} className="flex max-w-[calc(100%-360px)] shrink-0" />
        </div>
    );
}

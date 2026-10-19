// Home: the conversation with the account's coordinator. Empty, it asks what to
// take care of in the landing page's voice, with a few quiet starts; once there
// is a thread, it is the thread, with the composer pinned below. Until the page
// knows which (a device opening the chat for the first time), it shows neither.
// Turns that came from a phone or an inbox are captioned where they arrived, and
// Connect (top left) lists those ways in. The first message carries the composer from
// the middle of the page to its place under the thread. Arriving from an agent
// page, the thread opens on that agent being set up. The conversation is the
// coordinator's own, or the one a platform registers for accounts its rollout opens it to.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { ArrowUpRight, Brain } from 'lucide-react';
import { AgentChatComposer } from '~/components/chat/AgentChatComposer';
import { ChatReferenceChip } from '~/components/chat/ChatReferenceChip';
import { preloadMarkdownRenderer } from '~/components/chat/MarkdownRendererLazy';
import { CoordinatorTranscript } from '~/components/coordinator/CoordinatorTranscript';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { CoordinatorMemories } from '~/components/dashboard/CoordinatorMemories';
import { NodeMark } from '~/components/dashboard/primitives';
import { Skeleton } from '~/components/ui/skeleton';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';
import { Status } from '~/components/coordinator/inline/primitives';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { useCredentialList } from '~/hooks/useCachedCredentialList';
import { useAttachmentTray } from '~/hooks/useChatAttachments';
import { useCoordinatorChat } from '~/hooks/useCoordinatorChat';
import { useScaffoldArrival } from '~/hooks/useScaffoldArrival';
import { useStickToBottom } from '~/hooks/useStickToBottom';
import type { ChatReference } from '~/lib/agentChat';
import { consumePendingAsk, onAskNoClick } from '~/lib/askNoClick';
import { useFeatureGate, useFeatureGatesKnown } from '~/lib/featureGates';
import { cn } from '~/lib/utils';
import { PhoneBarActions, useInPhoneShell } from './AppShell';
import { BUTTON_SECONDARY } from './buttons';
import { ComposerAddMenu, accountReference } from './ComposerAddMenu';
import { ConnectMenu } from './ConnectMenu';
import { hasPlatformCoordinatorChat, PlatformCoordinatorChat, usePlatformCoordinatorChat, type CoordinatorChat } from './coordinatorChat';
import { useConnectedAccounts } from './connections/accounts';
import { accountIcon } from './connections/ConnectedList';
import { SidePanel } from './SidePanel';
import { DISPLAY } from './titles';

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

const COMPOSER_TRANSITION = 'nc-composer';

// On the page's own background, so the thread scrolling under it never shows through.
const ICON_BUTTON =
    'inline-flex h-8 w-8 items-center justify-center rounded-full bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40';

/** The thread's outline, shown only if loading it takes long enough to notice. */
function ThreadLoading() {
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

export function CoordinatorHome() {
    // The thread's markdown renders from its own chunk: fetch it while the history is on its way.
    useEffect(preloadMarkdownRenderer, []);
    const known = useFeatureGatesKnown();
    const platform = useFeatureGate('coordinator_agent') && hasPlatformCoordinatorChat();
    // Which chat an account has is known once its gates are; until then, neither opens.
    if (hasPlatformCoordinatorChat() && !known) return <ThreadLoading />;
    if (!platform) return <CoordinatorChatPage useChat={useCoordinatorChat} />;
    return (
        <PlatformCoordinatorChat fallback={<ThreadLoading />}>
            <CoordinatorChatPage useChat={usePlatformCoordinatorChat} />
        </PlatformCoordinatorChat>
    );
}

function CoordinatorChatPage({ useChat }: { useChat: () => CoordinatorChat }) {
    const coordinator = useChat();
    const { messages, isStreaming, errorReason, conversationId, send, loaded } = coordinator;
    const inPhone = useInPhoneShell();
    const [draft, setDraft] = useState('');
    const files = useAttachmentTray(coordinator.upload);
    const [references, setReferences] = useState<ChatReference[]>([]);
    const { credentials } = useCredentialList();
    const [memoriesOpen, setMemoriesOpen] = useState(false);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const composerCard = useRef<HTMLDivElement>(null);
    const arrival = useScaffoldArrival(conversationId, coordinator.arrive);
    const { arriving } = arrival;
    // Until its note is in the thread, the agent being set up holds the thread open.
    const settingUp = !!arriving && !messages.some((m) => m.setup && m.setup.workflow_id === arriving.workflowId);
    const lastText = messages[messages.length - 1]?.text;
    const view = settingUp || messages.length > 0 ? 'thread' : loaded ? 'start' : 'loading';
    const empty = view === 'start';
    // Pinned to the newest message unless the reader scrolled up, including while a card that loads after its message
    // (a canvas, a list of numbers) grows the thread.
    const scroller = useStickToBottom([messages.length, lastText?.length ?? 0, isStreaming]);

    const { readyAttachments, uploading, clearAttachments } = files;
    const submit = useCallback(
        (text: string = draft, withContext = true) => {
            const go = () => {
                if (!send(text, withContext ? readyAttachments : [], withContext ? references : [])) return;
                setDraft('');
                if (withContext) {
                    clearAttachments();
                    setReferences([]);
                }
            };
            // The first message moves the composer from the middle of the page to the foot of the thread.
            if (empty) withViewTransition(go);
            else go();
        },
        [draft, send, empty, readyAttachments, references, clearAttachments]
    );

    const addReference = useCallback((reference: ChatReference) => {
        setReferences((prev) => (prev.some((r) => r.kind === reference.kind && r.id === reference.id) ? prev : [...prev, reference]));
        requestAnimationFrame(() => textareaRef.current?.focus());
    }, []);

    // An account's chip reads as Connections names it, in its app's logo, wherever it shows; an automation's
    // keeps its name and mark.
    const accounts = useConnectedAccounts(credentials);
    const accountById = useMemo(() => new Map(accounts.map((a) => [a.credential.id, a])), [accounts]);
    const referenceDisplay = useCallback(
        function referenceDisplay(reference: ChatReference) {
            const account = reference.kind === 'account' ? accountById.get(reference.id) : undefined;
            if (!account) return undefined;
            const { Icon, iconColor } = accountIcon(account.credential);
            return { label: accountReference(account).label, mark: <BrandIcon Icon={Icon} iconColor={iconColor} className="h-3.5 w-3.5" /> };
        },
        [accountById]
    );

    const draftAndFocus = useCallback((text: string) => {
        setDraft(text);
        requestAnimationFrame(() => textareaRef.current?.focus());
    }, []);

    // Ready to type on arrival, where that doesn't pop a phone keyboard.
    useEffect(() => {
        if (conversationId && window.matchMedia('(pointer: fine)').matches) textareaRef.current?.focus();
    }, [conversationId]);

    // "Ask NoClick" from another page (or a card) lands here as a draft, with what it points at.
    useEffect(() => {
        const take = () => {
            const ask = consumePendingAsk();
            if (!ask) return;
            if (ask.references) setReferences(ask.references);
            draftAndFocus(ask.text);
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

    const hasContext = readyAttachments.length > 0 || references.length > 0;
    // A file that failed to upload holds the send until it's removed; the message never goes out without it.
    const failed = files.attachments.some((a) => a.status === 'error');
    const composer = (
        <AgentChatComposer
            value={draft}
            onChange={setDraft}
            onSubmit={() => submit()}
            placeholder={empty ? 'Describe a task, or ask anything' : 'Message NoClick'}
            inputDisabled={!conversationId}
            sendDisabled={(!draft.trim() && !hasContext) || uploading || failed || !conversationId || isStreaming}
            textareaRef={textareaRef}
            transitionName={COMPOSER_TRANSITION}
            size={empty ? 'tall' : 'default'}
            attachments={files.attachments}
            onAddFiles={files.addFiles}
            onRemoveAttachment={files.removeAttachment}
            cardRef={composerCard}
            addMenu={
                <ComposerAddMenu
                    anchorRef={composerCard}
                    side={empty ? 'bottom' : 'top'}
                    disabled={!conversationId}
                    onAddFiles={files.addFiles}
                    listFiles={coordinator.listFiles}
                    onAttach={files.addReady}
                    onReference={addReference}
                />
            }
            tray={
                references.length > 0
                    ? references.map((r) => (
                          <ChatReferenceChip
                              key={`${r.kind}:${r.id}`}
                              reference={r}
                              mark={referenceDisplay(r)?.mark}
                              onRemove={() => setReferences((prev) => prev.filter((x) => x !== r))}
                          />
                      ))
                    : undefined
            }
            className={empty && !inPhone ? 'px-0 pb-0 pt-0 sm:px-0' : undefined}
        />
    );

    const memories = (
        <>
            <SidePanel open={memoriesOpen} onOpenChange={setMemoriesOpen} title="Memories" description="What NoClick remembers. Only you can see them.">
                <CoordinatorMemories transport={coordinator.memories} />
            </SidePanel>
            <UpgradePopup isOpen={!!arrival.planLimitError} onOpenChange={(open) => !open && arrival.dismissPlanLimit()} errorMessage={arrival.planLimitError ?? ''} />
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
            <div className={cn(DISPLAY, 'leading-[1.02]')}>
                <h1 className="text-foreground">What should I take care of?</h1>
            </div>
        );
        const starters = (className?: string) =>
            STARTERS.map(({ title, detail, mark, prompt }) => (
                <StarterCard key={title} title={title} detail={detail} mark={mark} disabled={!conversationId} onTry={() => submit(prompt, false)} className={className} />
            ));

        // A phone keeps the composer where the thumb is, as the thread does.
        if (inPhone) {
            return (
                <div className="flex h-full flex-col" data-testid="coordinator-home">
                    {corners}
                    <div className="flex min-h-0 flex-1 flex-col justify-center px-6 text-[36px]">{headline}</div>
                    <div className="flex snap-x gap-2.5 overflow-x-auto scroll-px-4 px-4 pb-3 scrollbar-hide">{starters('w-[228px] shrink-0 snap-start')}</div>
                    {composer}
                    {memories}
                </div>
            );
        }

        return (
            <div className="relative flex h-full flex-col" data-testid="coordinator-home">
                {corners}
                <div className="relative min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
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
        <div className="relative flex h-full flex-col" data-testid="coordinator-home">
            {corners}
            <div ref={scroller.ref} onScroll={scroller.onScroll} className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                <div className={cn('mx-auto w-full max-w-3xl px-5 pb-10 sm:px-6', inPhone ? 'pt-4' : 'pt-14')}>
                    <CoordinatorTranscript messages={messages} isStreaming={isStreaming} errorReason={errorReason} referenceDisplay={referenceDisplay} useJobs={coordinator.followJobs} />
                    {settingUp && (
                        <div className={messages.length ? 'mt-6' : undefined}>
                            <Status state="working">Setting up {arriving.name}</Status>
                        </div>
                    )}
                </div>
            </div>
            {composer}
            {memories}
        </div>
    );
}

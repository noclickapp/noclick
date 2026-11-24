// The Chat page's Beside: Work's own card and rail beside NoClick's conversation, everything at work at a glance. Every open ask leads it
// as a Needs you group, each with its one action (Review a held purchase or deletion, in a dialog over the chat; Raise
// cap; Connect an account) and a title that jumps to its card in the thread, so nothing waits buried in scrollback; it
// clears as the backend's frames say the ask was answered. Under it, the helpers NoClick handed work to (an app's
// coding agent, the children of a build), as Work's rail rows: opening one puts its conversation (Work's activity log)
// in the column beside the chat. Placed as Work places it: a card at the column's top right where it fits (the thread
// and composer keep their text clear of it), else a pill at the top; on a phone a pill in the bar and the rail as a
// sheet. The chat's loops (`/loop`) run there too, each with when it runs next and its Stop. Nothing shows while
// nothing needs the person or works for them. The chat's own agent is never one of its helpers.
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useReportHeld } from '@/sdk/held';
import { useSlot } from '@/slots';
import { useAgentsAtWork, stopWork } from '../useAgentsAtWork';
import { coordinatorAgent } from '@/screens/work/coordinatorAgent';
import type { NoClick } from 'noclick';
import { WorkMotion } from '@/screens/work/agents/AgentRing';
import { useAgentFaces, useAgents } from '@/screens/work/agents/reads';
import { useConversationSandbox } from '@/screens/work/profile/reads';
import {
    BesideCard,
    BesidePill,
    BesideRail,
    CARD_MIN_PANE,
    cardReserve,
    ConversationFacts,
    MIN_COLUMN,
    RAIL_ROOM,
    RailPanel,
    RailSheet,
    StopBeside,
    useFresh,
    type BesideAsk,
    type RowLook,
} from '@/screens/work/conversation/Beside';
import { isLive, type BesideItem } from '@/screens/work/conversation/besideItems';
import { useLoops } from '@/screens/work/conversation/useLoops';
import { liveTurn } from '@/lib/agentThread/thread';
import { CONVERSATION_CSS } from '@/screens/work/conversation/styles';
import { PhoneBarActions, useInPhoneShell } from '@/ui/phoneBar';
import { ChatSourceContext, type ChatBesideProps } from '../source';
import { APPROVAL_REVIEW } from '../slots';
import type { ChannelMember } from '@/screens/channels/types';
import { TooltipProvider } from '@/ui/tooltip';
import { HelperColumn, useWatching } from './HelperColumn';
import { besideOf, type Helper, type NeedsYou } from './model';
import { useBrowserControl } from '@/screens/work/browser/useConversationBrowser';
import { NeedsContext } from './needs';
import { useChatThread } from '../thread';

/** The Chat page's lane at its widest (max-w-3xl) less its padding. */
const CHAT_LANE_TEXT = 720;

/** The chat's own agent's id, once the chat has found it (its conversation is known); null before. */
function useOwnAgentId(client: NoClick): string | null {
    const found = !!useContext(ChatSourceContext)?.conversationId;
    const own = coordinatorAgent(client);
    return found && own.isHydrated ? own.id : null;
}

/** Scrolls the thread to the first card carrying one of `refs` and lights it a moment; false where none is drawn. */
export function jumpToCard(refs: readonly string[]): boolean {
    for (const ref of refs) {
        const el = document.querySelector<HTMLElement>(`[data-card-refs~="${ref.replace(/"/g, '')}"]`);
        if (!el) continue;
        const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
        el.scrollIntoView?.({ block: 'center', behavior: still ? 'auto' : 'smooth' });
        if (!still) el.animate?.([{ backgroundColor: 'hsl(var(--foreground) / 0.08)' }, { backgroundColor: 'transparent' }], { duration: 1400, easing: 'ease-out' });
        return true;
    }
    return false;
}

/** An ask as the card and the rail list it: its action (a held call's Review opens it here where the host reviews held
 *  calls, else its page), and where its title goes (its card, else its helper). */
function askOf(need: NeedsYou, draft: (text: string) => void, watch: (helper: Helper) => void, review: ((approvalId: string) => void) | null): BesideAsk {
    const { ask, refs, helper } = need;
    const act = ask && (need.approval && review ? { label: ask.label, onClick: () => review(need.key) } : ask.href ? { label: ask.label, href: ask.href } : { label: ask.label, onClick: () => draft(ask.draft ?? '') });
    return {
        key: need.key,
        title: need.title,
        line: need.line,
        action: act || null,
        onJump:
            refs.length || helper
                ? () => {
                      if (!jumpToCard(refs) && helper) watch(helper);
                  }
                : undefined,
    };
}

export function ChatBeside({ client, draft, aside, width, onReserve }: ChatBesideProps & { client: NoClick }) {
    const { state, session, turns, jobs } = useChatThread();
    const Review = useSlot(APPROVAL_REVIEW);
    // Its own id once its session is known, which every read of it here names.
    const found = useOwnAgentId(client);
    const own = session ? found : null;
    const work = useAgentsAtWork(client, turns, jobs, own);
    const browser = useBrowserControl()?.browser ?? null;
    const { needs, items: helpers } = useMemo(() => besideOf(work, Date.now(), browser), [work, browser]);
    const loops = useLoops(own, own ? session : null, liveTurn(state.thread)?.operationId ?? null);
    const items = useMemo(() => [...helpers, ...loops], [helpers, loops]);
    const store = useContext(NeedsContext);
    useEffect(() => store?.set({ needs, draft }), [store, needs, draft]);
    const phone = useInPhoneShell();
    const [helper, watch] = useWatching();
    const [rail, setRail] = useState(false);
    const [stopping, setStopping] = useState<BesideItem | null>(null);
    const reportHeld = useReportHeld({ client });
    // Each Review opens the dialog afresh, on its ask.
    const [review, setReview] = useState<{ on: string; session: number } | null>(null);
    const sessions = useRef(0);
    const openReview = useCallback((on: string) => setReview({ on, session: ++sessions.current }), []);
    const held = useMemo(() => needs.flatMap((n) => (n.approval ? [n.approval] : [])), [needs]);
    const fresh = useFresh(items);
    const faces = useAgentFaces();
    const { data: agents } = useAgents();
    const sandbox = useConversationSandbox(own ?? '', own ? session : null).data;

    const shown = !!own && (items.length > 0 || needs.length > 0);
    const cardFits = !phone && width >= CARD_MIN_PANE;
    const railOpen = rail && shown && !phone;
    const sheetOpen = rail && shown && phone;
    const railBeside = railOpen && width - RAIL_ROOM >= MIN_COLUMN;
    const cardShown = shown && cardFits && !railOpen;
    const reserve = railBeside ? RAIL_ROOM : cardShown ? cardReserve(width, CHAT_LANE_TEXT) : 0;
    useEffect(() => onReserve(reserve), [reserve, onReserve]);
    useEffect(() => () => onReserve(0), [onReserve]);

    const asks = useMemo(() => needs.map((n) => askOf(n, draft, watch, Review ? openReview : null)), [needs, draft, watch, openReview, Review]);
    // Where the chat's agent runs, as Work's card says it of any conversation: only once it runs somewhere.
    const facts = own && sandbox ? <ConversationFacts agent={coordinatorAgent(client)} conversation={session ?? ''} changes={[]} /> : null;
    const face: ChannelMember = (own && faces.get(own)) || { id: own ?? 'noclick', kind: 'agent', name: 'NoClick', agentId: own ?? undefined, noclick: true };
    const look = (b: BesideItem): RowLook =>
        b.kind === 'loop'
            ? { harness: null, runsOn: null }
            : {
                  face: faces.get(b.id) ?? { id: b.id, kind: 'agent', name: b.agent?.name ?? 'An agent', agentId: b.id },
                  harness: null,
                  runsOn: agents?.find((a) => a.id === b.id)?.model ?? null,
              };
    const open = (b: BesideItem | null) => {
        if (b?.kind === 'loop') return; // its runs are this session's turns
        // Where the rail covers the chat, the helper's session takes the reader from it.
        if (phone || !railBeside) setRail(false);
        if (b) watch({ agentId: b.id });
    };
    const stop = async (b: BesideItem) => {
        setStopping(null);
        try {
            if (b.loop) {
                await b.loop.wakeup.cancel();
                toast('Stopped the loop');
                return;
            }
            if (!b.agent?.jobId) return;
            await stopWork(client, b.agent.jobId);
            toast(`Stopped ${b.agent.name}’s task`);
        } catch (error) {
            if (reportHeld(error, b.agent ? `Stop ${b.agent.name}’s task` : 'Stop the loop')) return;
            toast('Couldn’t stop it', { description: error instanceof Error ? error.message : String(error) });
        }
    };
    const railProps = {
        items,
        asks,
        facts,
        face,
        look,
        selected: helper?.agentId ?? null,
        onSelect: open,
        stoppable: (b: BesideItem) => isLive(b) && (b.kind === 'loop' || !!b.agent?.jobId),
        onStop: setStopping,
        fresh,
        // NoClick's helpers and the account's asks, not one conversation's subagents.
        title: 'Beside it',
    };
    const pill = own && <BesidePill agentId={own} conversation={session ?? ''} items={items} asks={asks} facts={facts} phone={phone} onOpenRail={() => setRail(true)} />;

    return (
        <TooltipProvider delayDuration={300}>
            <WorkMotion />
            <style>{CONVERSATION_CSS}</style>
            {/* Last in the bar, it gives way first: its count truncates before the bar runs off a narrow phone. */}
            {shown && phone && (
                <PhoneBarActions>
                    <span className="flex min-w-0 [&>button]:shrink">{pill}</span>
                </PhoneBarActions>
            )}
            {shown && !phone && !cardFits && !railOpen && <div className="absolute right-[60px] top-[14px] z-10 rounded-full bg-background">{pill}</div>}
            {cardShown && <BesideCard facts={facts} items={items} asks={asks} onOpen={() => setRail(true)} />}
            {railOpen && (
                <RailPanel>
                    <BesideRail {...railProps} onClose={() => setRail(false)} />
                </RailPanel>
            )}
            {sheetOpen && (
                <RailSheet onClose={() => setRail(false)}>
                    <BesideRail {...railProps} phone onClose={() => setRail(false)} />
                </RailSheet>
            )}
            <StopBeside item={stopping} onClose={() => setStopping(null)} onStop={(b) => void stop(b)} />
            {Review && <Review key={review?.session ?? 0} open={!!review} approvals={held} openOn={review?.on ?? null} onClose={() => setReview(null)} />}
            {helper && <HelperColumn helper={helper} aside={aside} phone={phone} watch={watch} onClose={() => watch(null)} />}
        </TooltipProvider>
    );
}

/** The Beside bound to the chat's platform client, as the chat hands it to the page. */
export function chatBesideFor(client: NoClick) {
    return function Beside(props: ChatBesideProps) {
        return <ChatBeside client={client} {...props} />;
    };
}

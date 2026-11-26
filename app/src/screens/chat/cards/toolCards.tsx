// Which card a tool call draws under the turn that made it: a call draws once it has answered, by its host's card
// ahead of all that matches it (a refused call's way past it), else the card named for its tool, else the first of the
// host's cards and then the chat's own (table.tsx) that matches what it answered; a card that follows live work draws
// while its call runs too. Calls that only look things up draw nothing: the reply says what they found. Web searches
// are the exception: the turn's pages are one Sources list above its cards.
import { Suspense, useMemo, type ReactNode } from 'react';
import { standing, useSlot } from '@/slots';
import { setupSubject, type SetupRef as CoordinatorSetupRef } from '@/lib/agentThread/thread';
import { AgentForAppsCard } from './AgentForAppsCard';
import { SourcesList, sourceKey, type Source } from '@/ui/chat/media';
import { Status } from '@/ui/chat/primitives';
import { cardRefsOf, list, str, type CoordinatorToolCall, type JsonObject } from '@/lib/toolCalls';
import type { CoordinatorJobs } from '@/lib/threadJobs';
import { MORE_CARDS, SETUP_CARD, type MoreCards } from '../slots';
import { CanvasesProvider, newestCanvases, useNewerCard, type SetupCardRef } from './canvases';
import { CARDS } from './table';
import { CoordinatorJobsContext, ThreadMovedContext } from './toolCardRegistry';

function cardFor(call: CoordinatorToolCall, turn: readonly CoordinatorToolCall[], more: MoreCards): ReactNode {
    const matched = [...more.cards, ...CARDS];
    if (call.running || !call.result) {
        const Live = matched.find((m) => m.whileRunning && m.match(call, turn))?.Card;
        return Live ? <Live call={call} turn={turn} /> : null;
    }
    const Ahead = more.ahead.find((m) => m.match(call, turn))?.Card;
    if (Ahead) return <Ahead call={call} turn={turn} />;
    // A search's pages join the turn's one Sources list (TurnCards), never a list of their own.
    if (call.tool === 'web_search') return null;
    const Card = more.named[call.tool] ?? matched.find((m) => m.match(call, turn))?.Card;
    return Card ? <Card call={call} turn={turn} /> : null;
}

/** Whether a call draws a card of its own: one named for its tool, or one matched by what it answered. */
export function drawsCard(call: CoordinatorToolCall, turn: readonly CoordinatorToolCall[]): boolean {
    const more = standing(MORE_CARDS);
    return !!more.named[call.tool] || [...more.cards, ...CARDS].some((m) => m.match(call, turn));
}

const LINK = /https?:\/\/[^\s<>()[\]"'`]+/g;

/** Every page the turn's web searches found, once each, the ones the reply links to first: a search returns more
 *  than the answer used, and searches in one turn overlap. */
export function turnSources(calls: readonly CoordinatorToolCall[], text = ''): Source[] {
    const cited = new Set((text.match(LINK) ?? []).map((url) => sourceKey(url.replace(/[.,;:!?]+$/, ''))));
    const pages = new Map<string, Source>();
    for (const call of calls) {
        if (call.tool !== 'web_search' || call.running) continue;
        for (const r of list(call.result, 'results')) {
            const row = r as JsonObject;
            const url = str(row, 'url');
            if (url && !pages.has(sourceKey(url))) pages.set(sourceKey(url), { url, title: str(row, 'title') ?? '' });
        }
    }
    const all = [...pages];
    return [...all.filter(([key]) => cited.has(key)), ...all.filter(([key]) => !cited.has(key))].map(([, source]) => source);
}

/** What the cards under a thread's turns read, for any transcript that draws them (the Chat page's, an agent's
 *  conversation in Work): the work the turns started (`jobs`), what changes as the thread moves on (`moved`), and
 *  which card about each automation is the newest, drawn in full. `cards`: every card, a note's setup and the turns'
 *  calls, in thread order. */
export function CardsProvider({ cards, jobs, moved, children }: { cards: readonly (CoordinatorToolCall | SetupCardRef)[]; jobs: CoordinatorJobs; moved: unknown; children: ReactNode }) {
    const canvases = useMemo(() => newestCanvases(cards, jobs), [cards, jobs]);
    return (
        <CoordinatorJobsContext.Provider value={jobs}>
            <ThreadMovedContext.Provider value={moved}>
                <CanvasesProvider value={canvases}>{children}</CanvasesProvider>
            </ThreadMovedContext.Provider>
        </CoordinatorJobsContext.Provider>
    );
}

/** The card under a setup note; `id` is its place among the thread's cards, so a newer one about the same automation
 *  (set up for another client, or built again) folds it. An agent an agents page made is the chat's own card; an
 *  automation's is its host's. */
export function SetupNoteCard({ id, setup }: { id: string; setup: CoordinatorSetupRef }) {
    const Card = useSlot(SETUP_CARD);
    const newer = useNewerCard(id, setupSubject(setup));
    if (setup.kind === 'agent_for_apps')
        return (
            <div className="mt-3" data-testid="coordinator-setup-card" data-folded={newer ? '' : undefined}>
                <AgentForAppsCard setup={setup} folded={!!newer} />
            </div>
        );
    if (!Card) return null;
    return (
        <div className="mt-3" data-testid="coordinator-setup-card" data-folded={newer ? '' : undefined}>
            <Suspense fallback={<Status state="working">Loading</Status>}>
                <Card setup={setup} newer={newer} />
            </Suspense>
        </div>
    );
}

export function TurnCards({ calls, text }: { calls: readonly CoordinatorToolCall[]; text?: string }) {
    const more = useSlot(MORE_CARDS);
    const sources = turnSources(calls, text);
    const cards = calls.flatMap((call) => {
        const card = cardFor(call, calls, more);
        // What the card is about (an approval, an operation, an agent), for a link elsewhere on the page to find it.
        return card ? [<div key={call.id} data-card-refs={cardRefsOf(call).join(' ') || undefined} className="rounded-2xl">{card}</div>] : [];
    });
    if (!sources.length && !cards.length) return null;
    return (
        <div className="mt-3 flex flex-col gap-2.5" data-testid="coordinator-cards">
            {sources.length > 0 && <SourcesList sources={sources} />}
            {cards}
        </div>
    );
}

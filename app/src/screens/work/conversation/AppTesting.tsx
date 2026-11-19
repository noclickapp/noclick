// App testing in an agent's chat: the one quiet line each switch leaves
// ("Atlas turned on app testing for this task · about $0.44/hour while it works", "… off · ran 18 min, $0.13", the
// owner's Allow or Not now), with What's this? and the way to the agent's profile under a line that turned it on, and
// the card that asks the owner first (Allow, Not now, Allow from now on). The card answers through the question's own
// route, and once answered it gives way to the line its answer left; the word Docker stays out of both but for those
// who know the term.
import { Layers } from 'lucide-react';
import { useState } from 'react';
import type { AppTestingNote } from '@/lib/agentThread/thread';
import { useHumanRequest } from '@/screens/humans/useHumanRequest';
import { useWorkClient } from '../client';
import { GlyphTile, InlineCard, PILL_PRIMARY, PILL_SECONDARY, Receipt } from '@/ui/chat/primitives';
import { str, type CoordinatorToolCall } from '@/lib/toolCalls';

const ALLOW = 'Allow';
const ALLOW_ALWAYS = 'Allow from now on';
const NOT_NOW = 'Not now';
const INLINE_ACT = 'underline decoration-foreground/30 underline-offset-[3px] transition-colors hover:text-foreground hover:decoration-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm';

/** One switch, as its line in the chat. `onProfile` opens the agent's profile, where its owner chooses. */
export function AppTestingLine({ note, agentName, onProfile }: { note: AppTestingNote; agentName: string; onProfile?: () => void }) {
    const [explained, setExplained] = useState(false);
    const turnedOn = note.state === 'on' || note.state === 'allowed';
    return (
        <div data-row="app-testing" className="px-1 py-1.5">
            <div className="flex items-start gap-2 rounded-2xl px-3 py-2 text-[12.5px] leading-[1.45] text-muted-foreground ring-1 ring-inset ring-border dark:ring-foreground/[0.08]">
                <Layers aria-hidden className="mt-[2px] h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                    <span className="font-medium text-foreground">{note.lead}</span>
                    {note.detail && <> · {note.detail}</>}
                </span>
            </div>
            {turnedOn && (
                <p className="mt-1 pl-3 text-xs text-muted-foreground">
                    <button type="button" aria-expanded={explained} onClick={() => setExplained((open) => !open)} className={INLINE_ACT}>
                        What’s this?
                    </button>
                    {onProfile && (
                        <>
                            {' · '}
                            <button type="button" onClick={onProfile} className={INLINE_ACT}>
                                Change in {agentName}’s profile
                            </button>
                        </>
                    )}
                </p>
            )}
            {turnedOn && explained && (
                <div className="mt-2 grid gap-1.5 rounded-2xl bg-foreground/[0.04] px-3.5 py-3 text-[13px] leading-relaxed text-foreground" data-testid="app-testing-explained">
                    <p>
                        {agentName} starts your app and a test database on a bigger computer to check its work, the way a developer would, and turns it off as soon as the tests are done. It only does this when a task needs it.
                    </p>
                    {note.reason && <p className="text-muted-foreground">This time: {note.reason}.</p>}
                    <p className="text-xs text-muted-foreground">This is Docker, for those who know the term.</p>
                </div>
            )}
        </div>
    );
}

/** The agent asked its owner first (`app_testing` under Ask first): Allow, Not now, and Allow from now on (which lets
 *  it turn app testing on by itself after this). */
export function AppTestingAskCard({ call }: { call: CoordinatorToolCall }) {
    const { question, unreadable, answering, failure, answer } = useHumanRequest(useWorkClient(), str(call.result, 'request_id') ?? '');
    const [always, setAlways] = useState(false);
    const title = str(call.result, 'title') ?? 'It needs to run a test database to check your app';
    const detail = str(call.result, 'detail');
    const reason = str(call.result, 'reason');
    const status = question?.status ?? 'pending';
    // Answered (or withdrawn), the line its answer left in the chat says what came of it.
    if (status === 'answered' || status === 'canceled') return null;
    if (status === 'expired') return <Receipt tone="info">Nobody answered in time · app testing stayed off</Receipt>;
    if (unreadable && !question) return <Receipt tone="info">Asked · {title}</Receipt>;
    const mine = question ? question.owner_can_answer !== false : true;
    const ready = !!question && !answering;
    return (
        <div data-testid="app-testing-ask">
            <InlineCard
                lead={
                    <GlyphTile>
                        <Layers className="h-4 w-4" />
                    </GlyphTile>
                }
                title={title}
                meta={detail ? `${detail}, nothing while idle` : undefined}
                actions={
                    mine ? (
                        <>
                            <button type="button" className={PILL_PRIMARY} disabled={!ready} onClick={() => void answer({ choice: always ? ALLOW_ALWAYS : ALLOW })}>
                                Allow
                            </button>
                            <button type="button" className={PILL_SECONDARY} disabled={!ready} onClick={() => void answer({ choice: NOT_NOW })}>
                                Not now
                            </button>
                            <span className="ml-auto text-xs text-muted-foreground">Uses Docker</span>
                        </>
                    ) : undefined
                }
            >
                {reason && <p className="text-[13px] leading-relaxed text-muted-foreground">It’s for this: {reason}.</p>}
                {mine ? (
                    <label className="mt-2 flex w-fit cursor-pointer items-center gap-2 text-[12.5px] text-muted-foreground">
                        <input type="checkbox" checked={always} onChange={(e) => setAlways(e.target.checked)} className="h-[15px] w-[15px] accent-foreground" />
                        Allow from now on
                    </label>
                ) : (
                    <p className="mt-2 text-[12.5px] text-muted-foreground">Waiting for their answer</p>
                )}
            </InlineCard>
            {failure && <p className="mt-2 text-[13px] text-red-600 dark:text-red-400">{failure}</p>}
        </div>
    );
}

// A harness subagent's own box, under its log in the pane: the conversation's box scoped to it. Its harness takes
// messages only into its main session, so what you write goes there, the main session told whom it's for, and the
// box says so ("Through Wirefern"); its foot names the subagent's harness and where it stands, and what it asks you
// tucks out above. Once it's over the box says so and hands the question to main ("Ask main about it").
import { useEffect, useState } from 'react';
import { CornerDownRight } from 'lucide-react';
import type { HarnessName, HarnessRequest, MessageSubagent, RequestDecision } from 'noclick';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { HarnessMark, harnessLabel } from '../agents/harness';
import { Elapsed } from './Activity';
import { isLive, type BesideItem } from './besideItems';
import { Composer } from './Composer';
import type { Mentionable } from './menus';
import { LANE } from './styles';

/** "3h ago", "just now": how long since it ended. */
function agoOf(at: number, now: number): string {
    const minutes = Math.round((now - at) / 60_000);
    if (minutes < 2) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    return hours < 48 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

/** Where what you write goes, said in a line with why on hover: the main session, which passes it on. */
export function ThroughMain({ mainName, harness }: { mainName: string; harness: HarnessName | null }) {
    const runsOn = harness ? harnessLabel(harness) : 'Its harness';
    return (
        <ShortcutTooltip label={`${runsOn} takes messages into its main session only, so ${mainName} reads yours, for this subagent, and passes it on.`}>
            {/* A button for its tooltip alone: focus says why, as hover does. */}
            <button
                type="button"
                data-testid="subagent-reach"
                className="me-1 inline-flex h-7 min-w-0 shrink cursor-default items-center gap-1.5 rounded-full px-2 text-xs text-muted-foreground outline-none transition-colors hover:bg-foreground/[0.04] hover:text-foreground focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
            >
                <CornerDownRight className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                <span className="truncate">Through {mainName}</span>
            </button>
        </ShortcutTooltip>
    );
}

/** Its harness and where it stands, in the place the agent's model control takes in main's box. */
function Standing({ item, harness, model }: { item: BesideItem; harness: HarnessName | null; model: string | null }) {
    const needs = item.status === 'needs';
    return (
        <span className="mr-1 inline-flex min-w-0 items-center gap-1.5 text-[13px]" data-testid="subagent-standing">
            {harness && <HarnessMark harness={harness} className="h-3.5 w-3.5" />}
            <span className="shrink-0 font-medium">{model ?? (harness ? `${harnessLabel(harness)} subagent` : 'Subagent')}</span>
            <span className={cn('truncate', needs ? 'font-medium text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                ·{' '}
                {needs ? (
                    'Needs you'
                ) : (
                    <>
                        Running <Elapsed from={item.startedAt} />
                    </>
                )}
            </span>
        </span>
    );
}

export interface SubagentBoxProps {
    item: BesideItem;
    /** The agent whose subagent it is: its main session is where what you write goes. */
    mainName: string;
    harness: HarnessName | null;
    /** What it waits on you for (its harness's asks from within it), oldest first. */
    requests: HarnessRequest[];
    mentionables: () => Promise<Mentionable[]>;
    onTell: (subagent: MessageSubagent, text: string) => Promise<boolean>;
    onAnswer: (request: HarnessRequest, decision: RequestDecision, options?: { note?: string; answers?: Record<string, string | string[]> }) => void;
    /** Back to main, with this subagent in its box to ask about. */
    onAskMain: () => void;
}

export function SubagentBox({ item, mainName, harness, requests, mentionables, onTell, onAnswer, onAskMain }: SubagentBoxProps) {
    const call = item.call;
    const model = call && typeof call.arguments.model === 'string' ? call.arguments.model : null;
    if (isLive(item) && call)
        return (
            <Composer
                key={item.id}
                agentName="this subagent"
                harnessLabel={harness ? harnessLabel(harness) : 'Its harness'}
                working={item.status === 'running'}
                ready
                commands={null}
                queued={[]}
                requests={requests}
                subagents={[]}
                onShowSubagents={() => undefined}
                mentionables={mentionables}
                model={<Standing item={item} harness={harness} model={model} />}
                onControl={() => undefined}
                drawer={null}
                onSend={({ text }) => onTell({ id: item.id, title: item.title }, text)}
                onStop={() => undefined}
                onUnqueue={async () => null}
                onAnswer={onAnswer}
                upload={() => Promise.reject(new Error('A subagent takes words alone.'))}
                // What it asks you is answered to its request itself, not through main: the box then says nothing of main.
                scope={{ lead: requests.some((r) => r.status === 'pending') ? null : <ThroughMain mainName={mainName} harness={harness} />, placeholder: 'Message this subagent…' }}
            />
        );
    return <FinishedBox item={item} mainName={mainName} onAskMain={onAskMain} />;
}

/** Once it's over: what happened, and the way to ask main, which has what it found. */
function FinishedBox({ item, mainName, onAskMain }: { item: BesideItem; mainName: string; onAskMain: () => void }) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const t = setInterval(() => setNow(Date.now()), 30_000);
        return () => clearInterval(t);
    }, []);
    const said = item.status === 'failed' ? 'It failed' : item.status === 'stopped' ? 'It stopped' : 'It finished';
    return (
        <div className="relative shrink-0 px-5 pb-4" data-testid="subagent-finished">
            <div className={LANE}>
                <div className="flex min-h-[60px] items-center gap-3 rounded-[26px] bg-composer pl-5 pr-2.5 ring-1 ring-inset ring-border dark:ring-foreground/[0.09]">
                    <p className="min-w-0 flex-1 truncate text-[13.5px] text-muted-foreground">
                        <span className="text-foreground">{said}</span>
                        {item.endedAt !== null && ` ${agoOf(item.endedAt, now)}`} · {mainName} has what it {item.status === 'failed' ? 'got to' : 'found'}
                    </p>
                    <button type="button" onClick={onAskMain} className={cn(BUTTON_PRIMARY, 'h-9 shrink-0 px-4 text-[13px]')}>
                        Ask main about it
                    </button>
                </div>
            </div>
        </div>
    );
}

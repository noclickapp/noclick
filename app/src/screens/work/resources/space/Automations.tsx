// A space's automations, drawn with the Automations page's own parts: its cards (each a picture of its graph) or its
// rows, as the page's toggle picks, each with what's the space's own: what people here get of it, how its last run
// went and when it runs next, Run now for whoever here may run it, and its menu. Opening one goes where it opens on the
// Automations page, its canvas, for the account; anyone else, whose canvas has none of the account's, opens its page.
import { CalendarClock, Play, UsersRound } from 'lucide-react';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { relTime } from '@/lib/formatters';
import { AutomationCard, AutomationGrid, CardAction, CARD_ACTION_TRIGGER, CardBadge, CardPill } from '@/screens/workflows/browser/WorkflowBrowserCards';
import { AutomationRow, RowBadge, RowList } from '@/screens/workflows/browser/WorkflowBrowserList';
import type { BrowserLayoutMode } from '@/screens/workflows/browser/LayoutToggle';
import { useBrowserPreference } from '@/screens/workflows/browser/useBrowserPreference';
import { useWorkClient } from '../../client';
import { useWork } from '../../context';
import { useWorkViewer } from '../../viewer';
import { runAutomation } from './actions';
import { levelWords, RUNS_IT, type Thing } from './data';
import { enterOpens, ThingMenu } from './parts';
import type { Pane } from './pane';

/** Cards or rows, one choice for every space, kept in this browser as the Automations page keeps its own. */
export function useAutomationsLayout(): [BrowserLayoutMode, (mode: BrowserLayoutMode) => void] {
    return useBrowserPreference<BrowserLayoutMode>('spaces', 'browserLayoutMode', 'grid');
}

/** Where an automation opens for whoever reads the space: on its canvas, as on the Automations page, for the account
 *  (where its host opens one); null for a person who joined the space, whose canvas has none of the account's. */
export function useAutomationCanvas(): ((automation: { id: string; name: string }) => void) | null {
    const { openWorkflow } = useWork();
    const viewer = useWorkViewer();
    return openWorkflow && viewer.type === 'account' ? openWorkflow : null;
}

/** Whether whoever reads the space runs the automation: the account, or someone it's shared with to run. */
export const runsIt = (t: Thing) => !!t.automation?.level && RUNS_IT.includes(t.automation.level);

type RunState = 'none' | 'running' | 'failed' | 'succeeded';

/** How its last run went, in a few words; null where whoever reads the space doesn't see its runs. */
export function lastRun(t: Thing, now: string): { text: string; state: RunState; error: string | null } | null {
    const run = t.automation?.lastRun;
    if (run === undefined) return null;
    if (!run) return { text: 'No run yet', state: 'none', error: null };
    if (run.status === 'running') return { text: 'Running now', state: 'running', error: null };
    const ago = run.at ? relTime(run.at, now) : '';
    const when = ago === 'now' ? ' just now' : ago ? ` ${ago}` : '';
    return run.status === 'failed' ? { text: `Failed${when}`, state: 'failed', error: run.error } : { text: `Ran${when}`, state: 'succeeded', error: null };
}

/** When a schedule runs it next, in a few words; null where none does. */
export function nextRun(t: Thing, now: string): string | null {
    if (!t.automation?.nextRun) return null;
    const at = relTime(t.automation.nextRun, now);
    return at === 'now' ? 'Runs any moment' : `Next ${at}`;
}

const DOT: Record<RunState, string> = {
    none: 'ring-[1.5px] ring-inset ring-foreground/40',
    running: 'bg-foreground/70 animate-pulse',
    failed: 'bg-red-500',
    succeeded: 'bg-emerald-500',
};
const FAILED_TEXT = 'text-red-600 dark:text-red-400';

/** What people here get of it (the account reads its people's level; a person their own), as its badge says it. */
function heldHere(t: Thing, account: boolean): { words: string; title: string } | null {
    const level = account ? t.link?.membersLevel : t.automation?.level;
    if (!t.link || !level) return null;
    const words = levelWords('automation', level);
    return { words, title: `${account ? 'Everyone here' : 'You'}: ${words.toLowerCase()}` };
}

/** The whole of what its facts shorten, for their tooltip. */
function factsTitle(t: Thing, now: string): string {
    const last = lastRun(t, now);
    return [last && (last.error ? `${last.text}: ${last.error}` : last.text), nextRun(t, now)].filter(Boolean).join(' · ');
}

/** A card or row's view of it: what the Automations page's parts draw. */
const shown = (t: Thing) => ({
    id: t.ref,
    name: t.name,
    description: t.automation?.description ?? '',
    graph_preview: t.automation?.preview ?? undefined,
    node_types: t.automation?.preview ? [...new Set(t.automation.preview.nodes.map((n) => n.type))] : undefined,
});

/** Runs it now: a page's pill, or a row's, its words left out where the row is narrow. */
export function RunNowButton({ spaceId, t, onPage }: { spaceId: string; t: Thing; onPage?: boolean }) {
    const client = useWorkClient();
    return (
        <button
            type="button"
            aria-label={`Run ${t.name} now`}
            onClick={(e) => {
                e.stopPropagation();
                void runAutomation(client, spaceId, t);
            }}
            className={
                onPage
                    ? BUTTON_SECONDARY
                    : 'inline-flex h-7 w-7 shrink-0 items-center justify-center gap-1.5 rounded-full text-[12.5px] font-medium text-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.06] @xl:w-auto @xl:px-3 dark:ring-foreground/[0.14]'
            }
        >
            <Play className={onPage ? 'h-4 w-4' : 'h-3 w-3'} strokeWidth={onPage ? 1.9 : 2.2} />
            <span className={onPage ? undefined : 'hidden @xl:inline'}>Run now</span>
        </button>
    );
}

export function SpaceAutomations({ pane, things, layout }: { pane: Pane; things: Thing[]; layout: BrowserLayoutMode }) {
    const client = useWorkClient();
    const canvas = useAutomationCanvas();
    const account = useWorkViewer().type === 'account';
    const open = (t: Thing) => (canvas ? canvas({ id: t.ref, name: t.name }) : pane.open(t));
    const opener = (t: Thing) => ({ role: 'button', tabIndex: 0, 'aria-label': t.name, 'data-testid': `automation-${t.ref}`, onClick: () => open(t), onKeyDown: enterOpens(() => open(t)) });
    if (layout === 'list') {
        return (
            <RowList>
                {things.map((t) => {
                    const last = lastRun(t, pane.now);
                    const held = heldHere(t, account);
                    return (
                        <AutomationRow
                            key={t.key}
                            {...opener(t)}
                            automation={shown(t)}
                            facts={[last && <span className={cn(last.state === 'failed' && FAILED_TEXT)}>{last.text}</span>, nextRun(t, pane.now)]}
                            factsTitle={factsTitle(t, pane.now)}
                            badge={
                                held && (
                                    // A phone keeps its room for the name: its page and menu say the level.
                                    <span className="hidden sm:contents">
                                        <RowBadge title={held.title}>{held.words}</RowBadge>
                                    </span>
                                )
                            }
                            actions={
                                <>
                                    {runsIt(t) && <RunNowButton spaceId={pane.spaceId} t={t} />}
                                    <ThingMenu pane={pane} t={t} className="opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 [@media(hover:none)]:opacity-100" />
                                </>
                            }
                        />
                    );
                })}
            </RowList>
        );
    }
    return (
        <AutomationGrid data-testid="space-automations-grid">
            {things.map((t) => {
                const last = lastRun(t, pane.now);
                const next = nextRun(t, pane.now);
                const held = heldHere(t, account);
                return (
                    <AutomationCard
                        key={t.key}
                        {...opener(t)}
                        automation={shown(t)}
                        actions={
                            <>
                                {runsIt(t) && <CardAction label={`Run ${t.name} now`} icon={Play} onClick={() => void runAutomation(client, pane.spaceId, t)} />}
                                <ThingMenu pane={pane} t={t} className={CARD_ACTION_TRIGGER} />
                            </>
                        }
                        factsTitle={factsTitle(t, pane.now)}
                        facts={
                            <>
                                {last && (
                                    <CardPill icon={<span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', DOT[last.state])} />}>
                                        <span className={cn(last.state === 'failed' && FAILED_TEXT)}>{last.text}</span>
                                    </CardPill>
                                )}
                                {next && (
                                    <CardPill icon={<CalendarClock className="w-3 h-3 shrink-0 text-muted-foreground" />} className="shrink-0">
                                        {next}
                                    </CardPill>
                                )}
                            </>
                        }
                        badge={
                            held && (
                                <CardBadge title={held.title}>
                                    <span className="flex items-center gap-1">
                                        <UsersRound className="h-3 w-3" strokeWidth={2} />
                                        {held.words}
                                    </span>
                                </CardBadge>
                            )
                        }
                    />
                );
            })}
        </AutomationGrid>
    );
}

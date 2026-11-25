// Work's Agents list: the New agent pill held at the top, a search, chips past six agents (All · Running · Needs you ·
// Failed), the space's NoClick pinned first (yours in your personal space), then one list sorted needs-you first, each agent's state drawn as a ring round its avatar and its running
// tool call as its line, and a menu on each row (Rename, Delete). Read from GET /v1/agents and /v1/agents/states, kept current
// by the backend's frames.
import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import { MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { BotPlus } from '@/ui/BotPlus';
import { useInPhoneShell } from '@/ui/phoneBar';
import { useIntent } from '@/ui/useIntent';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { prefetchConversation } from '../conversation/useConversation';
import { useSpaceNoClick } from '../intro';
import { NEW_AGENT } from '../place';
import { ActionRow, FindField, LIST_TOP } from '../ui';
import { AgentRing } from './AgentRing';
import { useDeleteAgent } from './DeleteAgent';
import { renamable, useRenameDialog } from './rename';
import { HarnessMark, harnessLabel } from './harness';
import { agentFaces, factsOf, keptByNoClick, noclickNaming, useAgentFrames, useAgents, useAgentStates, useHelperIds, useNoClickId, useSpaceNoClicks } from './reads';
import { byAttention, chipCounts, CHIPS, CHIPS_ABOVE, entryOf, foundIn, matchRanges, termsOf, type Chip, type Entry, type Field } from './states';
import { Tip } from '../tooltip';

export const LIST_ROW =
    'flex w-full items-center gap-2.5 rounded-lg pl-2 pr-2 text-left transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';
export const LIST_CURRENT = 'bg-foreground/[0.07] hover:bg-foreground/[0.07]';
const CHIP_KEY = 'nc-work-agents-chip';
const QUIET = 'px-2.5 pb-2 pt-1 text-[13px] text-muted-foreground max-md:text-[14px]';

export interface AgentsListProps {
    spaceId: string | null;
    selectedAgentId: string | null;
    onOpen(agentId: string): void;
    onNew(): void;
}

/** The chip you're on, kept per device; storage that's blocked or empty starts on All. */
function useChip(): [Chip, (chip: Chip) => void] {
    const [chip, setChip] = useState<Chip>('all');
    useEffect(() => {
        try {
            const saved = window.localStorage.getItem(CHIP_KEY);
            if (CHIPS.some((c) => c.id === saved)) setChip(saved as Chip);
        } catch {
            // Private windows and blocked storage keep All.
        }
    }, []);
    const choose = (next: Chip) => {
        setChip(next);
        try {
            window.localStorage.setItem(CHIP_KEY, next);
        } catch {
            // Not kept, but still chosen for this visit.
        }
    };
    return [chip, choose];
}

/** The page's clock, a tick a second while something runs, so a running agent's time moves. */
function useNow(ticking: boolean): number {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        if (!ticking) return;
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, [ticking]);
    return ticking ? now : Date.now();
}

/** Every place a term falls in the text, bolded; `rest` styles the letters around them. */
function marked(text: string, terms: string[], bold: string, rest?: string): ReactNode {
    const ranges = terms.length ? matchRanges(text, terms) : [];
    if (!ranges.length) return text;
    const parts: ReactNode[] = [];
    const plain = (from: number, to: number) => parts.push(rest ? <span key={`r${from}`} className={rest}>{text.slice(from, to)}</span> : text.slice(from, to));
    let at = 0;
    ranges.forEach(([from, to], i) => {
        if (from > at) plain(at, from);
        parts.push(
            <b key={i} className={bold}>
                {text.slice(from, to)}
            </b>
        );
        at = to;
    });
    if (at < text.length) plain(at, text.length);
    return parts;
}

/** The space's agents as its list and its empty pane show them: each one's row (its ring, its line), needs-you first;
 *  their faces; the clock their lines read; and `loading` until they're read. NoClick's own agent works across the
 *  account, its conversation the Chat page, and each space's NoClick answers in its #noclick: neither is one of a
 *  space's agents, so neither is a row (the list pins the space's own above them). NoClick's helpers aren't yours:
 *  never listed. Resources lists the same agents (your home's). `ticking`: a working agent's line counts its time. */
export function useAgentEntries(spaceId: string | null, { ticking = true }: { ticking?: boolean } = {}) {
    const agents = useAgents();
    const states = useAgentStates(spaceId);
    const noclick = useNoClickId();
    const noclicks = useSpaceNoClicks();
    const helpers = useHelperIds();
    const facts = useMemo(() => new Map((agents.data ?? []).map((a) => [a.id, factsOf(a, noclicks)])), [agents.data, noclicks]);
    const faces = useMemo(() => agentFaces([...facts.values()]), [facts]);
    const now = useNow(ticking && (states.data ?? []).some((s) => s.state === 'working'));
    const entries = useMemo(
        () =>
            (states.data ?? [])
                .filter((s) => !keptByNoClick(s.raw) && !helpers.has(s.agentId))
                .map((s) => entryOf(s, facts.get(s.agentId), now))
                .sort(byAttention),
        [states.data, helpers, facts, now]
    );
    // Until the agents are read it can't tell NoClick's own from the rest.
    const loading = !states.data || (noclick === undefined && agents.error === undefined);
    return { states, noclick, facts, faces, now, entries, loading };
}

export function AgentsList({ spaceId, selectedAgentId, onOpen, onNew }: AgentsListProps) {
    const phone = useInPhoneShell();
    useAgentFrames();
    const { states, noclick, facts, faces, now, entries, loading } = useAgentEntries(spaceId);
    const client = useWorkClient();
    // A row the pointer rests on reads ahead the session it opens.
    const intent = useIntent((id) => {
        if (id !== selectedAgentId) prefetchConversation(client, id);
    });
    // The space's own NoClick is pinned above its agents (yours in your personal space), never counted, chipped or
    // deleted with them.
    const spaceNoClick = useSpaceNoClick(spaceId);
    const pinnedId = spaceId ? spaceNoClick?.agentId : noclick;
    const pinnedNaming = spaceId ? spaceNoClick : noclickNaming(null);
    const [query, setQuery] = useState('');
    const [chip, setChip] = useChip();
    const root = useRef<HTMLDivElement>(null);
    const input = useRef<HTMLInputElement>(null);
    // The shell opens a new agent's draft in an agent's place.
    const drafting = selectedAgentId === NEW_AGENT;

    const terms = termsOf(query);
    const searching = terms.length > 0;
    const pinnedState = pinnedId ? states.data?.find((st) => st.agentId === pinnedId) : undefined;
    const pinnedEntry = pinnedState ? entryOf(pinnedState, undefined, now) : null;
    const pinned: Entry | null =
        pinnedId && pinnedNaming
            ? {
                  ...(pinnedEntry ?? { id: pinnedId, harness: 'sdk' as const, role: '', status: 'idle' as const, needs: 0, ago: 0, startedAt: now }),
                  name: pinnedNaming.name,
                  line: pinnedEntry && pinnedEntry.status !== 'idle' ? pinnedEntry.line : pinnedNaming.line,
              }
            : null;
    const pinnedShown = pinned && (!searching || foundIn(pinned, terms, harnessLabel(pinned.harness))) ? pinned : null;

    const counts = chipCounts(entries);
    const chipsShown = entries.length > CHIPS_ABOVE;
    const current = chipsShown ? CHIPS.find((c) => c.id === chip)! : CHIPS[0];
    // A chip with nothing in it stays out, unless it's the one you're on (so it can say it's empty).
    const chips = CHIPS.filter((c) => c.id === 'all' || counts[c.id] > 0 || c.id === current.id);

    // A search keeps what matched, best first, each with the field it matched in; the chip narrows it.
    const found = new Map<string, { score: number; field: Field } | null>();
    const hits = searching
        ? entries
              .filter((e) => {
                  const f = foundIn(e, terms, harnessLabel(e.harness));
                  found.set(e.id, f);
                  return !!f;
              })
              .sort((x, y) => found.get(x.id)!.score - found.get(y.id)!.score || byAttention(x, y))
        : entries;
    const shownRows = hits.filter(current.holds);
    const deleting = useDeleteAgent(shownRows.map((e) => e.id));
    const renaming = useRenameDialog();
    const rows = () => Array.from(root.current?.querySelectorAll<HTMLButtonElement>('li[data-agent] > button:first-child') ?? []);

    // ⇧⌘O starts a new agent (a page can't take ⌘N from the browser); no hint shows it.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'o') {
                e.preventDefault();
                onNew();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onNew]);

    // `/` anywhere in the list's column finds an agent (never in a field, where it's a command or a letter).
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
            const target = e.target as HTMLElement;
            const column = root.current?.closest('aside') ?? root.current;
            if (!column?.contains(target) || target.closest('input, textarea, [contenteditable="true"]')) return;
            e.preventDefault();
            input.current?.focus({ preventScroll: true });
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    // Up and down move between the rows, Home and End to the ends, and up from the first goes back to the search.
    useEffect(() => {
        const el = root.current;
        if (!el) return;
        const onKey = (e: KeyboardEvent) => {
            const list = rows();
            const at = list.indexOf(e.target as HTMLButtonElement);
            if (at < 0 || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
            e.preventDefault();
            if (e.key === 'ArrowUp' && at === 0) input.current?.focus();
            else list[e.key === 'Home' ? 0 : e.key === 'End' ? list.length - 1 : Math.min(list.length - 1, Math.max(0, at + (e.key === 'ArrowDown' ? 1 : -1)))]?.focus();
        };
        el.addEventListener('keydown', onKey);
        return () => el.removeEventListener('keydown', onKey);
    }, []);
    const onSearchKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            rows()[0]?.focus();
        } else if (e.key === 'Enter') rows()[0]?.click();
        else if (e.key === 'Escape') {
            if (query) setQuery('');
            else input.current?.blur();
        }
    };

    const row = (e: Entry, pin = false) => {
        const where = found.get(e.id)?.field;
        const soft = 'font-semibold text-foreground';
        const line =
            where === 'job' ? (
                marked(e.role, terms, soft)
            ) : where === 'harness' ? (
                <span className="inline-flex items-center gap-1.5 align-top">
                    <HarnessMark harness={e.harness} className="h-3.5 w-3.5" />
                    {marked(harnessLabel(e.harness), terms, soft)}
                </span>
            ) : (
                marked(e.line, terms, soft)
            );
        const face = pin ? { id: e.id, kind: 'agent' as const, name: e.name, agentId: e.id, noclick: true } : (faces.get(e.id) ?? { id: e.id, kind: 'agent' as const, name: e.name });
        const kept = pin || facts.get(e.id)?.noclick;
        return (
            <li key={e.id} data-agent={e.id} data-pinned={pin || undefined} className="group relative">
                <button
                    type="button"
                    onClick={() => onOpen(e.id)}
                    {...intent(e.id)}
                    aria-current={e.id === selectedAgentId ? 'page' : undefined}
                    className={cn(LIST_ROW, 'gap-3 py-2', !kept && 'pr-10', e.id === selectedAgentId && LIST_CURRENT)}
                >
                    <AgentRing member={face} status={e.status} size={32} />
                    <span data-rail-text className="min-w-0 flex-1">
                        <span data-name className={cn('block truncate text-[14px] text-foreground max-md:text-[16px]', e.needs ? 'font-semibold' : 'font-medium')}>{marked(e.name, terms, 'font-semibold text-foreground', 'font-normal text-foreground/65')}</span>
                        <span className="block truncate text-[12.5px] text-muted-foreground max-md:text-[14px]">{line}</span>
                    </span>
                    {e.needs > 0 && <Count n={e.needs} />}
                </button>
                {/* NoClick keeps its own agents: nothing to rename, delete or remove. */}
                {!kept && (
                    <DropdownMenu>
                        <Tip label="More">
                            <DropdownMenuTrigger
                                aria-label={`More for ${e.name}`}
                                className="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full text-muted-foreground opacity-0 transition-[opacity,background-color,color] hover:bg-foreground/[0.07] hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100 data-[state=open]:bg-foreground/[0.08] data-[state=open]:text-foreground data-[state=open]:opacity-100 max-md:right-0 max-md:h-10 max-md:w-10 max-md:opacity-100 [@media(hover:none)]:opacity-100"
                            >
                                <MoreHorizontal className="h-4 w-4" />
                            </DropdownMenuTrigger>
                        </Tip>
                        <DropdownMenuContent align="end" sideOffset={4} className="min-w-[200px] rounded-xl p-1">
                            {renamable({ id: e.id }) && (
                                <DropdownMenuItem onSelect={() => renaming.ask({ id: e.id, name: e.name })} className="gap-2.5 rounded-lg px-2.5 py-2 text-[14px]">
                                    <Pencil className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
                                    Rename
                                </DropdownMenuItem>
                            )}
                            <DropdownMenuItem onSelect={() => deleting.ask({ id: e.id, name: e.name })} className="gap-2.5 rounded-lg px-2.5 py-2 text-[14px] text-red-600 dark:text-red-400">
                                <Trash2 className="h-4 w-4" strokeWidth={2} />
                                Delete agent
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </li>
        );
    };
    const toAll = (n: number, label: string) => (
        <button type="button" onClick={() => setChip('all')} className="rounded-full px-2.5 py-1 text-[13px] font-medium text-foreground transition-colors hover:bg-foreground/[0.05]">
            {label.replace('{n}', String(n))}
        </button>
    );

    let body: ReactNode;
    if (states.error !== undefined && !states.data)
        body = (
            <div>
                <p className={QUIET}>Couldn’t load your agents.</p>
                <button type="button" onClick={() => void states.refresh()} className="rounded-full px-2.5 py-1 text-[13px] font-medium text-foreground transition-colors hover:bg-foreground/[0.05]">
                    Try again
                </button>
            </div>
        );
    else if (loading) body = <ListSkeleton />;
    else if (!entries.length) body = searching && !pinnedShown ? <p className={QUIET}>No agent called “{query.trim()}”</p> : searching ? null : <p className={QUIET}>No agents here yet. Make one, and it shows up here.</p>;
    else if (shownRows.length) body = <ul className="flex flex-col gap-px">{shownRows.map((e) => row(e))}</ul>;
    // Found only in the pinned NoClick: nothing more to say.
    else if (searching && pinnedShown) body = null;
    else if (!searching)
        body = (
            <div>
                <p className={QUIET}>{current.empty}</p>
                {toAll(entries.length, 'Show all {n}')}
            </div>
        );
    else if (hits.length)
        // Found, but not under this chip: never offer to make one that exists.
        body = (
            <div>
                <p className={QUIET}>
                    No {current.noun} called “{query.trim()}”
                </p>
                {toAll(hits.length, hits.length === 1 ? 'See the 1 in All' : 'See the {n} in All')}
            </div>
        );
    else
        body = (
            <div>
                <p className={QUIET}>No agent called “{query.trim()}”</p>
                <button
                    type="button"
                    onClick={() => {
                        setQuery('');
                        onNew();
                    }}
                    className={cn(LIST_ROW, 'gap-3 py-2')}
                >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-dashed border-foreground/35 text-muted-foreground">
                        <Plus className="h-4 w-4" strokeWidth={1.75} />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-foreground">New agent named {query.trim()}</span>
                </button>
            </div>
        );

    return (
        <div ref={root} data-testid="agents-list">
            {/* On a phone the way to add sits beside the search (FindField's `add`), not in a row of its own. */}
            {!phone && (
                <div className={LIST_TOP}>
                    <ActionRow icon={BotPlus} iconSize={20} label="New agent" onClick={onNew} pressed={drafting} keys="Shift+Meta+O" />
                </div>
            )}
            {drafting && (
                <div aria-current="page" className="mb-2 flex w-full items-center gap-3 rounded-lg bg-foreground/[0.07] py-2 pl-2 pr-2">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-dashed border-foreground/35 text-muted-foreground">
                        <Plus className="h-4 w-4" strokeWidth={1.75} />
                    </span>
                    <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-medium text-foreground">New agent</span>
                        <span className="block truncate text-[12.5px] text-muted-foreground">Draft · made when you send</span>
                    </span>
                </div>
            )}
            <FindField
                inputRef={input}
                value={query}
                onChange={setQuery}
                onKeyDown={onSearchKey}
                placeholder="Find an agent"
                keys="/"
                add={phone ? { label: 'New agent', icon: Plus, onClick: onNew, pressed: drafting } : undefined}
            />
            {chipsShown && (
                <div className="-mx-2 mb-2 flex gap-1 overflow-x-auto px-2 scrollbar-hide max-md:-mt-1 max-md:mb-1 max-md:px-4 max-md:py-1" role="group" aria-label="Show">
                    {chips.map((c) => {
                        const on = c.id === current.id;
                        return (
                            <button
                                key={c.id}
                                type="button"
                                aria-pressed={on}
                                onClick={() => setChip(c.id)}
                                className={cn(
                                    // On a phone a finger's height: the row around it takes the taps above and below the pill.
                                    "relative inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-[7px] text-[12px] transition-colors max-md:h-8 max-md:px-2.5 max-md:text-[14px] max-md:after:absolute max-md:after:-inset-y-1 max-md:after:inset-x-0 max-md:after:content-['']",
                                    on ? 'bg-foreground/[0.12] font-medium text-foreground ring-1 ring-inset ring-foreground/[0.14]' : 'text-muted-foreground ring-1 ring-inset ring-border hover:bg-foreground/[0.04] hover:text-foreground'
                                )}
                            >
                                {c.label}
                                {/* All needs no count; one waiting on you reads in full ink, as the rail's badge stands out. */}
                                {c.id !== 'all' && <span className={cn('tabular-nums', c.id === 'needs' && counts.needs && !on ? 'font-semibold text-foreground' : 'opacity-70')}>{counts[c.id]}</span>}
                            </button>
                        );
                    })}
                </div>
            )}
            {pinnedShown && states.data && <ul className="mb-px flex flex-col">{row(pinnedShown, true)}</ul>}
            {body}
            {deleting.dialog}
            {renaming.dialog}
        </div>
    );
}

export function Count({ n }: { n: number }) {
    return <span data-count className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-foreground px-1.5 text-[11px] font-semibold tabular-nums leading-none text-background">{n}</span>;
}

function ListSkeleton() {
    return (
        <ul className="flex flex-col gap-px" aria-label="Loading your agents">
            {[0, 1, 2].map((i) => (
                <li key={i} className="flex items-center gap-3 px-2 py-2">
                    <span className="h-8 w-8 shrink-0 animate-pulse rounded-full bg-foreground/[0.07]" />
                    <span data-rail-text className="flex-1 space-y-1.5">
                        <span className="block h-3 w-24 animate-pulse rounded-full bg-foreground/[0.07]" />
                        <span className="block h-2.5 w-40 animate-pulse rounded-full bg-foreground/[0.05]" />
                    </span>
                </li>
            ))}
        </ul>
    );
}


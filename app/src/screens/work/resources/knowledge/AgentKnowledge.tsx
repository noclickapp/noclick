// An agent's skills and memories on its profile, kept quiet: two count pills, each opening the list of what's
// attached (its own memory counts among its memories), with Attach, a way to all of them in Resources, a row to open
// each one's page and a ✕ to detach it.
import { useState } from 'react';
import { ArrowUpRight, Plus, X } from 'lucide-react';
import type { Knowledge } from '@/screens/resources/knowledge';
import { MENU_SURFACE } from '@/ui/menus';
import { resourceAddress } from '@/screens/resources/kinds';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { useWork } from '../../context';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../../client';
import { AttachDialog, KnowledgeSheet } from './AttachDialog';
import { ICON_BUTTON, ItemMark, XS } from './parts';
import { detachWithUndo, titleOf, useKnowledge } from './store';

const COUNT_PILL =
    'inline-flex h-9 items-center gap-2 rounded-full bg-foreground/[0.06] px-4 text-[14px] text-foreground/85 transition-colors hover:bg-foreground/[0.1] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.1] data-[state=open]:text-foreground';

/** One skill or memory in a pill's list: its name over its description; the row opens its page, the ✕ detaches it. */
function KnowLine({ agentId, item, onOpen }: { agentId: string; item: Knowledge; onOpen: () => void }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const agent = k.agent(agentId);
    const owner = item.kind === 'memory' && item.agentId ? k.agent(item.agentId) : undefined;
    const mine = item.kind === 'memory' && item.agentId === agentId;
    return (
        <li className="group relative flex items-center gap-2.5 rounded-xl px-2.5 py-2 transition-colors hover:bg-foreground/[0.05]">
            <ItemMark kind={item.kind} className="h-7 w-7" iconClassName="h-[14px] w-[14px]" />
            <div className="min-w-0 flex-1 pr-6">
                <button
                    type="button"
                    onClick={onOpen}
                    className="block w-full truncate text-left text-[14px] leading-snug after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring"
                >
                    {titleOf(item, owner, agentId)}
                </button>
                <p className="truncate text-xs leading-snug text-muted-foreground">{item.description}</p>
            </div>
            {!mine && agent && (
                <button
                    type="button"
                    aria-label={`Detach ${titleOf(item, owner)}`}
                    onClick={() => void detachWithUndo(client, agent, item, titleOf(item, owner))}
                    className={cn(ICON_BUTTON, 'absolute right-1.5 top-1/2 z-[1] h-7 w-7 -translate-y-1/2 opacity-0 focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100')}
                >
                    <X className="h-3.5 w-3.5" />
                </button>
            )}
        </li>
    );
}

/** A count pill, as Connections' tabs draw one; it opens the list of what's attached, with Attach and a way to
 *  Resources, where every skill and memory lives. */
function KnowPill({ agentId, kind, items, onOpen, onAttach }: { agentId: string; kind: Knowledge['kind']; items: Knowledge[]; onOpen: (id: string) => void; onAttach: () => void }) {
    const [shown, setShown] = useState(false);
    const { openPage } = useWork();
    const label = kind === 'skill' ? 'Skills' : 'Memories';
    const noun = kind === 'skill' ? (items.length === 1 ? 'skill' : 'skills') : items.length === 1 ? 'memory' : 'memories';
    return (
        <Popover open={shown} onOpenChange={setShown}>
            <PopoverTrigger className={COUNT_PILL} data-testid={`agent-${kind}s`}>
                {label}
                <span className="tabular-nums text-muted-foreground">{items.length}</span>
            </PopoverTrigger>
            <PopoverContent
                align="start"
                sideOffset={6}
                collisionPadding={12}
                className={cn('work-rise flex max-h-[min(30rem,var(--radix-popover-content-available-height))] w-[340px] flex-col rounded-2xl p-1.5', MENU_SURFACE)}
            >
                <div className="flex items-center justify-between gap-3 py-1 pl-2.5 pr-1">
                    <p className="text-[13px] font-medium">
                        {items.length} {noun}
                    </p>
                    <button
                        type="button"
                        onClick={() => {
                            setShown(false);
                            onAttach();
                        }}
                        className={cn(XS, 'bg-foreground/[0.06] text-foreground/85 hover:bg-foreground/[0.1]')}
                    >
                        <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                        Attach
                    </button>
                </div>
                {items.length ? (
                    <ul className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                        {items.map((item) => (
                            <KnowLine
                                key={item.id}
                                agentId={agentId}
                                item={item}
                                onOpen={() => {
                                    setShown(false);
                                    onOpen(item.id);
                                }}
                            />
                        ))}
                    </ul>
                ) : (
                    <p className="px-2.5 pb-2 pt-1 text-[13px] leading-snug text-muted-foreground">
                        {kind === 'skill' ? 'None yet. A skill teaches it a way of working: a SKILL.md and the scripts it uses.' : 'None yet. A memory is notes it reads every turn, and can add to.'}
                    </p>
                )}
                {openPage && (
                    <button
                        type="button"
                        onClick={() => {
                            setShown(false);
                            openPage('resources', resourceAddress(kind === 'skill' ? 'skills' : 'memories'));
                        }}
                        className="mt-1 flex h-9 shrink-0 items-center gap-2 rounded-xl px-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
                    >
                        All {label.toLowerCase()} in Resources
                        <ArrowUpRight className="ml-auto h-3.5 w-3.5" strokeWidth={2} />
                    </button>
                )}
            </PopoverContent>
        </Popover>
    );
}

/** The profile's skills and memories: two count pills. Its own memory counts among its memories. */
export function AgentKnowledge({ agentId }: { agentId: string }) {
    const k = useKnowledge();
    const [picking, setPicking] = useState<Knowledge['kind'] | null>(null);
    const [open, setOpen] = useState<string | null>(null);
    const agent = k.agent(agentId);
    const known = (ids: string[]) => ids.map((id) => k.find(id)).filter((i): i is Knowledge => !!i);
    const skills = known(agent?.skills.map((s) => s.id) ?? []);
    const home = k.owns.find((m) => m.agentId === agentId);
    const memories = [...(home ? [home] : []), ...known(agent?.memories.map((m) => m.id) ?? [])];
    return (
        <section className="mt-6 flex flex-wrap gap-2" data-testid="agent-knowledge">
            <KnowPill agentId={agentId} kind="skill" items={skills} onOpen={setOpen} onAttach={() => setPicking('skill')} />
            <KnowPill agentId={agentId} kind="memory" items={memories} onOpen={setOpen} onAttach={() => setPicking('memory')} />
            {picking && agent && <AttachDialog agentId={agentId} initialTab={picking} onClose={() => setPicking(null)} onCreated={setOpen} />}
            {open && <KnowledgeSheet id={open} from={agentId} now={new Date().toISOString()} onClose={() => setOpen(null)} onOpen={setOpen} />}
        </section>
    );
}

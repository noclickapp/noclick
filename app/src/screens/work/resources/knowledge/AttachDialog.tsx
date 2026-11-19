// For an agent's profile: the account's skills and memories, searched, with what it has ticked and a memory's access
// set as it's ticked; Done writes its links in one change. And a skill's or memory's page over the view, from the
// right, as a deep page rather than a dialog.
import { useEffect, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { BookOpen, Check, Plus, Search, X } from 'lucide-react';
import { useWorkClient } from '../../client';
import { MAX_MEMORIES, setAgentLinks, type AgentRef, type Knowledge } from '@/screens/resources/knowledge';
import { HAIRLINE } from '@/ui/primitives';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { DisabledTip } from '../../tooltip';
import { ICON_BUTTON, ItemMark, list, PILL_FIELD } from './parts';
import { KnowledgePage } from './KnowledgePage';
import { NewMemoryDialog, NewSkillDialog } from './NewDialogs';
import { readLinksAgain, titleOf, useKnowledge, writeRefusal } from './store';

type Picked = { id: string; kind: Knowledge['kind']; pin?: number | null; writes?: boolean };

export function AttachDialog({ agentId, onClose, onCreated, initialTab = 'skill' }: { agentId: string; onClose: () => void; onCreated?: (id: string) => void; initialTab?: Knowledge['kind'] }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const agent = k.agent(agentId);
    const [tab, setTab] = useState<Knowledge['kind']>(initialTab);
    const [query, setQuery] = useState('');
    const [making, setMaking] = useState<Knowledge['kind'] | null>(null);
    const [busy, setBusy] = useState(false);
    const [picked, setPicked] = useState<Picked[]>(() => [
        ...(agent?.skills ?? []).map((s) => ({ id: s.id, kind: 'skill' as const, pin: s.pin })),
        ...(agent?.memories ?? []).map((m) => ({ id: m.id, kind: 'memory' as const, writes: m.writes })),
    ]);
    if (!agent) return null;
    const items: Knowledge[] = tab === 'skill' ? k.skills : [...k.memories, ...k.owns.filter((m) => m.agentId !== agent.id)];
    const q = query.trim().toLowerCase();
    const shown = q ? items.filter((i) => `${i.name ?? ''} ${i.description}`.toLowerCase().includes(q)) : items;
    const linkOf = (id: string) => picked.find((l) => l.id === id);
    const memoryCount = picked.filter((l) => l.kind === 'memory').length;
    const toggle = (item: Knowledge) => {
        if (linkOf(item.id)) setPicked(picked.filter((l) => l.id !== item.id));
        else if (item.kind === 'memory' && memoryCount >= MAX_MEMORIES) toast(`An agent reads up to ${MAX_MEMORIES} memories besides its own`, { description: 'Untick one, or put related notes in one memory.' });
        else setPicked([...picked, { id: item.id, kind: item.kind, writes: item.kind === 'memory' ? false : undefined }]);
    };
    const done = async (a: AgentRef) => {
        const before = new Set([...a.skills.map((s) => s.id), ...a.memories.map((m) => m.id)]);
        const after = new Set(picked.map((l) => l.id));
        const added = [...after].filter((id) => !before.has(id)).length;
        const removed = [...before].filter((id) => !after.has(id)).length;
        setBusy(true);
        try {
            await setAgentLinks(client, a, {
                skills: picked.filter((l) => l.kind === 'skill').map((l) => ({ id: l.id, pin: l.pin ?? null })),
                memories: picked.filter((l) => l.kind === 'memory').map((l) => ({ id: l.id, writes: !!l.writes })),
            });
        } catch (error) {
            toast.error(`Couldn’t change ${a.name}’s skills and memories`, { description: error instanceof Error ? error.message : String(error) });
            setBusy(false);
            return;
        }
        readLinksAgain();
        if (added || removed) toast(`${a.name} gets this from its next conversation`, { description: [added && `${added} attached`, removed && `${removed} detached`].filter(Boolean).join(', ') });
        onClose();
    };
    const made = (item?: Knowledge) => {
        setMaking(null);
        if (item) {
            onClose();
            onCreated?.(item.id);
        }
    };
    return (
        <>
            <ShellDialog
                open={!making}
                onOpenChange={(o) => !o && onClose()}
                title={`Attach to ${agent.name}`}
                description="Ticked ones reach it from its next conversation. Skills and memories stay in Resources; detaching never deletes one."
                mark={<BookOpen className="h-5 w-5" strokeWidth={1.75} />}
                size="md"
                testId="attach-picker"
                footer={
                    <div className="flex w-full items-center gap-2">
                        <button type="button" onClick={() => setMaking(tab)} className={BUTTON_GHOST}>
                            <Plus className="h-4 w-4" strokeWidth={2} />
                            New {tab === 'skill' ? 'skill' : 'memory'}
                        </button>
                        <span className="flex-1" />
                        <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                            Cancel
                        </button>
                        <button type="button" disabled={busy} onClick={() => void done(agent)} className={BUTTON_PRIMARY}>
                            Done
                        </button>
                    </div>
                }
            >
                <div className="flex flex-col gap-3">
                    <label className="relative block">
                        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} />
                        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={tab === 'skill' ? 'Search skills' : 'Search memories'} className={cn(PILL_FIELD, 'pl-10')} />
                    </label>
                    <div className="flex items-center gap-1">
                        {(['skill', 'memory'] as const).map((t) => (
                            <button
                                key={t}
                                type="button"
                                onClick={() => setTab(t)}
                                className={cn('inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] transition-colors', tab === t ? 'bg-foreground/[0.08] font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}
                            >
                                {t === 'skill' ? 'Skills' : 'Memories'}
                                <span className="tabular-nums text-muted-foreground">{t === 'skill' ? k.skills.length : k.memories.length + k.owns.length - 1}</span>
                            </button>
                        ))}
                        {tab === 'memory' && (
                            <span className="ml-auto text-xs text-muted-foreground">
                                {memoryCount} of {MAX_MEMORIES}, besides its own
                            </span>
                        )}
                    </div>
                    <ul className="-mx-2 max-h-[46vh] overflow-y-auto scrollbar-subtle">
                        {shown.map((item) => {
                            const link = linkOf(item.id);
                            const owner = item.kind === 'memory' && item.agentId ? k.agent(item.agentId) : undefined;
                            const others = k.usersOf(item).filter((u) => u.agent.id !== agent.id).map((u) => u.agent.name);
                            const writeNo = item.kind === 'memory' ? writeRefusal(agent, item, owner) : null;
                            return (
                                <li key={item.id} className="rounded-xl px-2 py-2 hover:bg-foreground/[0.04]">
                                    <button type="button" onClick={() => toggle(item)} className="flex w-full items-start gap-3 text-left" aria-pressed={!!link}>
                                        <span className={cn('mt-1 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border transition-colors', link ? 'border-foreground bg-foreground text-background' : 'border-foreground/30')}>
                                            {link && <Check className="h-3 w-3" strokeWidth={3} />}
                                        </span>
                                        <ItemMark kind={item.kind} className="h-7 w-7" />
                                        <span className="min-w-0 flex-1">
                                            <span className="block truncate text-sm font-medium">{titleOf(item, owner, agent.id)}</span>
                                            <span className="block truncate text-[13px] text-muted-foreground">{item.description}</span>
                                            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                                                {owner ? `${owner.name}’s own: only it writes, so ${agent.name} would read it` : others.length ? `Used by ${list(others)}` : 'No agent uses it yet'}
                                            </span>
                                        </span>
                                    </button>
                                    {link && item.kind === 'memory' && (
                                        <div className="ml-[58px] mt-1.5 flex items-center gap-1">
                                            {[
                                                { writes: false, label: 'Reads' },
                                                { writes: true, label: 'Reads and writes' },
                                            ].map((o) => (
                                                <DisabledTip key={o.label} label={o.writes ? writeNo : null} disabled={o.writes && !!writeNo}>
                                                    <button
                                                        type="button"
                                                        disabled={o.writes && !!writeNo}
                                                        onClick={() => setPicked(picked.map((l) => (l.id === item.id ? { ...l, writes: o.writes } : l)))}
                                                        className={cn(
                                                            'h-7 rounded-full px-2.5 text-xs transition-colors disabled:opacity-40',
                                                            !!link.writes === o.writes ? 'bg-foreground/[0.09] font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'
                                                        )}
                                                    >
                                                        {o.label}
                                                    </button>
                                                </DisabledTip>
                                            ))}
                                        </div>
                                    )}
                                </li>
                            );
                        })}
                        {!shown.length && <li className="px-2 py-6 text-center text-sm text-muted-foreground">{q ? `Nothing matches “${query}”.` : `The account has no ${tab === 'skill' ? 'skill' : 'memory'} yet.`}</li>}
                    </ul>
                </div>
            </ShellDialog>
            {making === 'skill' && <NewSkillDialog agent={agent.id} onClose={made} />}
            {making === 'memory' && <NewMemoryDialog agent={agent.id} onClose={made} />}
        </>
    );
}

function Sheet({ children, onClose, testId }: { children: ReactNode; onClose: () => void; testId?: string }) {
    return (
        <>
            <div className="fixed inset-0 z-[65] bg-foreground/[0.08] dark:bg-background/60" onClick={onClose} aria-hidden />
            <div data-testid={testId} className={cn('fixed inset-y-0 right-0 z-[66] flex w-full max-w-[880px] flex-col border-l bg-background shadow-2xl', HAIRLINE)}>
                {children}
            </div>
        </>
    );
}

/** A skill's or memory's page over the view, from the right; Escape or the backdrop closes it. */
export function KnowledgeSheet({ id, from, now, onClose, onOpen }: { id: string; from?: string; now: string; onClose: () => void; onOpen: (id: string) => void }) {
    const k = useKnowledge();
    const item = k.find(id);
    useEffect(() => {
        const key = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && !document.querySelector('[role="dialog"], [role="menu"]')) onClose();
        };
        window.addEventListener('keydown', key);
        return () => window.removeEventListener('keydown', key);
    }, [onClose]);
    return (
        <Sheet onClose={onClose} testId="knowledge-sheet">
            <div className={cn('flex h-12 shrink-0 items-center gap-2 border-b px-3 sm:px-4', HAIRLINE)}>
                <span className="truncate text-[13px] text-muted-foreground">{item?.kind === 'memory' ? 'Memory' : 'Skill'}</span>
                <button type="button" aria-label="Close" onClick={onClose} className={cn(ICON_BUTTON, 'ml-auto')}>
                    <X className="h-[18px] w-[18px]" />
                </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                <KnowledgePage id={id} from={from} now={now} onOpen={onOpen} onTrashed={onClose} />
            </div>
        </Sheet>
    );
}

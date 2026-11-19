// Starting a channel, in two steps. First its name (kept as Slack keeps them: lowercase words and dashes) and a
// one-line topic; then who's in it: one searchable list of your agents (the NoClick of where it is first, then your
// platform agents) and the space's people, what's picked gathered above it. Agents in it answer every message. In a workspace, a platform agent that isn't one of its members joins the workspace too.
import { useState, type FormEvent, type ReactNode } from 'react';
import { ArrowLeft, Check, Hash, Plus, Search, X } from 'lucide-react';
import { ShellDialog } from '@/ui/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { FIELD_LABEL, PILL_FIELD } from '@/ui/fields';
import { cn } from '@/ui/utils';
import { AgentChoiceRow } from './AgentChoiceRow';
import { MemberAvatar } from './avatars';
import type { AccountMenuUser } from '@/ui/accountParts';
import { agentGroups, channelSlug, hueFor } from './model';
import type { AgentChoice, PersonChoice } from './types';

export interface NewChannelInput {
    name: string;
    topic: string;
    agents: AgentChoice[];
    /** The people's user ids. */
    people: string[];
}

const SECTION = 'px-2 pb-1 pt-3 text-[12px] font-medium text-muted-foreground';
const ROW = 'group flex w-full items-center gap-3 rounded-[18px] px-2 py-2 text-left transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';

/** Whether every word typed is somewhere in `text`. */
const matches = (query: string, text: string) => query.toLowerCase().split(/\s+/).filter(Boolean).every((word) => text.toLowerCase().includes(word));

/** A round add button: + to add, a filled check once added. */
function AddToggle({ on }: { on: boolean }) {
    return (
        <span aria-hidden className={cn('grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors', on ? 'bg-foreground text-background' : 'text-muted-foreground ring-1 ring-inset ring-foreground/20 group-hover:text-foreground group-hover:ring-foreground/40')}>
            {on ? <Check className="h-3.5 w-3.5" strokeWidth={2.75} /> : <Plus className="h-3.5 w-3.5" strokeWidth={2.25} />}
        </span>
    );
}

/** Someone picked, as a chip that takes them out again. */
function Token({ label, face, onRemove }: { label: string; face: ReactNode; onRemove: () => void }) {
    return (
        <span className="inline-flex h-8 max-w-full items-center gap-1.5 rounded-full bg-foreground/[0.07] pl-1 pr-1 text-[13px] text-foreground">
            {face}
            <span className="truncate">{label}</span>
            <button type="button" aria-label={`Take out ${label}`} onClick={onRemove} className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-foreground/[0.08] hover:text-foreground">
                <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
        </span>
    );
}

const agentFace = (agent: AgentChoice, user: AccountMenuUser, size: 24 | 28) => (
    <MemberAvatar member={{ id: agent.id, kind: 'agent', name: agent.name, hue: hueFor(agent.id), ...(agent.noclick ? { noclick: true } : {}) }} user={user} size={size} />
);
const personFace = (person: PersonChoice, user: AccountMenuUser, size: 24 | 28) => <MemberAvatar member={{ id: person.id, kind: 'human', name: person.name }} user={user} size={size} />;

export function NewChannelDialog({
    open,
    onOpenChange,
    where,
    agents,
    people = [],
    agentsHref,
    user,
    onCreate,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** The workspace's name, for the title. */
    where: string;
    agents: AgentChoice[];
    /** The space's people besides you. */
    people?: PersonChoice[];
    agentsHref: string;
    user: AccountMenuUser;
    onCreate: (input: NewChannelInput) => Promise<void>;
}) {
    const [step, setStep] = useState<1 | 2>(1);
    const [name, setName] = useState('');
    const [topic, setTopic] = useState('');
    const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
    const [query, setQuery] = useState('');
    const [problem, setProblem] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const slug = channelSlug(name);

    const reset = () => {
        setStep(1);
        setName('');
        setTopic('');
        setPicked(new Set());
        setQuery('');
        setProblem(null);
    };
    const close = (next: boolean) => {
        if (busy) return;
        onOpenChange(next);
        if (!next) reset();
    };
    const toggle = (id: string) =>
        setPicked((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });

    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (!slug || busy) return;
        if (step === 1) return setStep(2);
        setBusy(true);
        setProblem(null);
        try {
            await onCreate({ name: slug, topic: topic.trim(), agents: agents.filter((a) => picked.has(a.id)), people: people.flatMap((p) => (picked.has(p.id) ? [p.id] : [])) });
            onOpenChange(false);
            reset();
        } catch (err) {
            setProblem(err instanceof Error ? err.message : 'Couldn’t start the channel.');
        } finally {
            setBusy(false);
        }
    };

    // NoClick first, then your platform agents, as every agent picker orders them.
    const ordered = agentGroups(agents).flatMap((group) => group.agents);
    const shownAgents = ordered.filter((a) => matches(query, [a.name, a.role, a.modelLine].join(' ')));
    const shownPeople = people.filter((p) => matches(query, `${p.name} ${p.detail ?? ''}`));
    const pickedAgents = ordered.filter((a) => picked.has(a.id));
    const pickedPeople = people.filter((p) => picked.has(p.id));
    const who = people.length ? 'Agents and people' : 'Agents';

    return (
        <ShellDialog
            open={open}
            onOpenChange={close}
            title={step === 1 ? 'Start a channel' : `Who’s in #${slug}?`}
            description={step === 1 ? `In ${where} · step 1 of 2` : `${who} from ${where} · step 2 of 2`}
            onSubmit={(e) => void submit(e)}
            testId="new-channel-dialog"
            footer={
                step === 1 ? (
                    <>
                        <button type="button" onClick={() => close(false)} className={BUTTON_GHOST}>
                            Cancel
                        </button>
                        <button type="submit" disabled={!slug} className={BUTTON_PRIMARY}>
                            Next: who’s in it
                        </button>
                    </>
                ) : (
                    <>
                        <button type="button" onClick={() => setStep(1)} disabled={busy} className={cn(BUTTON_GHOST, 'mr-auto')}>
                            <ArrowLeft className="h-4 w-4" strokeWidth={2} />
                            Back
                        </button>
                        <button type="submit" disabled={!slug || busy} className={BUTTON_PRIMARY}>
                            {busy ? 'Starting…' : `Start #${slug}`}
                        </button>
                    </>
                )
            }
        >
            {step === 1 ? (
                <div className="space-y-4 pb-2 pt-1">
                    <label className="block">
                        <span className={FIELD_LABEL}>Name</span>
                        <span className="relative block">
                            <Hash className="pointer-events-none absolute left-4 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-muted-foreground" strokeWidth={2} />
                            <input
                                // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens to name the channel
                                autoFocus
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                placeholder="launch-plans"
                                maxLength={80}
                                className={cn(PILL_FIELD, 'h-12 pl-10 text-[16px]')}
                            />
                        </span>
                        {name.trim() && slug !== name.trim() && <span className="mt-1.5 block px-4 text-[12.5px] text-muted-foreground">Saved as #{slug || '…'}</span>}
                    </label>
                    <label className="block">
                        <span className={FIELD_LABEL}>
                            Topic <span className="font-normal text-muted-foreground">· optional</span>
                        </span>
                        <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="What it’s for, in a line" maxLength={250} className={PILL_FIELD} />
                    </label>
                </div>
            ) : (
                <div className="pb-2 pt-1">
                    {agents.length || people.length ? (
                        <>
                            <span className="relative block">
                                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.8} />
                                <input
                                    // eslint-disable-next-line jsx-a11y/no-autofocus -- the step opens to find who's in it
                                    autoFocus
                                    value={query}
                                    onChange={(e) => setQuery(e.target.value)}
                                    placeholder={`Search ${who.toLowerCase()}`}
                                    aria-label={`Search ${who.toLowerCase()}`}
                                    className={cn(PILL_FIELD, 'h-9 pl-10 pr-9 text-[13.5px]')}
                                />
                                {query && (
                                    <button type="button" aria-label="Clear" onClick={() => setQuery('')} className="absolute right-1.5 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-foreground/[0.06]">
                                        <X className="h-3.5 w-3.5" />
                                    </button>
                                )}
                            </span>
                            {picked.size > 0 && (
                                <div className="mt-3 flex flex-wrap gap-1.5" data-testid="new-channel-picked">
                                    {pickedAgents.map((a) => (
                                        <Token key={a.id} label={a.name} face={agentFace(a, user, 24)} onRemove={() => toggle(a.id)} />
                                    ))}
                                    {pickedPeople.map((p) => (
                                        <Token key={p.id} label={p.name} face={personFace(p, user, 24)} onRemove={() => toggle(p.id)} />
                                    ))}
                                </div>
                            )}
                            <div className="-mx-2 mt-1 max-h-[340px] overflow-y-auto scrollbar-subtle">
                                {shownAgents.length > 0 && <p className={SECTION}>Agents · {shownAgents.length}</p>}
                                {shownAgents.map((agent) => (
                                    <button key={agent.id} type="button" role="checkbox" aria-checked={picked.has(agent.id)} onClick={() => toggle(agent.id)} className={ROW}>
                                        <AgentChoiceRow agent={agent} user={user} />
                                        <AddToggle on={picked.has(agent.id)} />
                                    </button>
                                ))}
                                {shownPeople.length > 0 && <p className={SECTION}>People · {shownPeople.length}</p>}
                                {shownPeople.map((person) => (
                                    <button key={person.id} type="button" role="checkbox" aria-checked={picked.has(person.id)} onClick={() => toggle(person.id)} className={ROW}>
                                        {personFace(person, user, 28)}
                                        <span className="min-w-0 flex-1">
                                            <span className="block truncate text-[14px] font-medium text-foreground">{person.name}</span>
                                            {person.detail && <span className="block truncate text-xs text-muted-foreground">{person.detail}</span>}
                                        </span>
                                        <AddToggle on={picked.has(person.id)} />
                                    </button>
                                ))}
                                {!shownAgents.length && !shownPeople.length && <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">No agent or person matches “{query}”.</p>}
                            </div>
                        </>
                    ) : (
                        <p className="text-[13px] leading-snug text-muted-foreground">
                            You have no agents yet.{' '}
                            <a href={agentsHref} className="font-medium text-foreground/80 underline decoration-foreground/25 underline-offset-[3px] hover:text-foreground">
                                Make one
                            </a>
                            , then add it here.
                        </p>
                    )}
                    {problem && (
                        <p role="alert" className="mt-3 text-[12.5px] text-red-600 dark:text-red-400">
                            {problem}
                        </p>
                    )}
                </div>
            )}
        </ShellDialog>
    );
}

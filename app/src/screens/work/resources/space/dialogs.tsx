// A space's Resources dialogs: adding the account's items to the space, making one (here where it can be made here,
// else the app's own page or a request to NoClick), a new channel, a delete that names everyone who loses it (a
// connection or a secret is removed for good, its access ending everywhere), and, from home, giving one to a space.
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Check, Hash, Plus, Search, Trash2, UsersRound } from 'lucide-react';
import { Agent, Bucket, Channel, Connection, Database, Machine, Project, Repo, Workflow } from 'noclick';
import { BUTTON_DANGER, BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { WorkspaceTile } from '@/screens/channels/workspaces';
import { FIELD_LABEL } from '@/ui/fields';
import { ShellDialog } from '@/ui/ShellDialog';
import { useWork } from '../../context';
import { cn } from '@/ui/utils';
import { resourceAddress } from '@/screens/resources/kinds';
import { useWorkV1 } from '../../agents/reads';
import { useWorkClient } from '../../client';
import { useWorkNav } from '../../nav';
import { useWorkViewer } from '../../viewer';
import { AddMachine } from '../inResources';
import { NewMemoryDialog, NewSkillDialog } from '../knowledge/NewDialogs';
import { AgentFace, PILL_FIELD } from '../knowledge/parts';
import { useKnowledge } from '../knowledge/store';
import { addToSpace, deleteThing, previewDelete, removedForGood, titleFor } from './actions';
import { useAutomationCanvas } from './Automations';
import { kindOf, LINK_KIND, readSpaceAgain, share, thingKey, useSpaceLinks, type SpaceKind, type SpaceShare, type Thing } from './data';
import { Lead, list, markOf } from './parts';
import type { Pane } from './pane';

type Candidate = Thing & { detail: string };

/** The account's items of a kind, as candidates to add (read only while the picker is open). */
function useAccountItems(kind: SpaceKind): { loading: boolean; items: Candidate[] } {
    const k = useKnowledge();
    const read = useWorkV1(`work:account/${kind}`, async (client): Promise<Candidate[]> => {
        const make = (ref: string, name: string, detail: string): Candidate => ({ key: thingKey(kind, ref), kind, ref, name, detail, link: null, usedBy: [] });
        switch (kind) {
            case 'agents':
                // NoClick's helpers work for it, not you: none is offered for a space.
                return (await Agent.list({ client })).filter((a) => !a.helper).map((a) => make(a.id, a.name, a.harness ?? ''));
            case 'connections':
                // By its id, as a space's link names it (an account connected in the app by `credential:<id>`), so one
                // shared already is known; a name would name another account of that name, or none.
                return (await Connection.list({ client })).map((c) => make(c.id, c.name, [c.integration, c.account].filter(Boolean).join(' · ')));
            case 'websites':
                return (await Project.list({ client })).map((p) => make(p.id, p.name, p.url ?? 'Website'));
            case 'databases':
                return (await Database.list({ client })).map((d) => make(d.id, d.name, 'Database'));
            case 'files':
                return (await Bucket.list({ client })).map((b) => make(b.id, b.name, 'Bucket'));
            case 'code':
                return (await Repo.list({ client })).map((r) => make(r.id, r.name, 'Repository'));
            case 'automations':
                // The account's own: one shared with it, or another account pays for, isn't its to share.
                return (await Workflow.list({ client })).filter((w) => w.access === 'owner').map((w) => make(w.id, w.name, w.description ?? 'Automation'));
            case 'machines':
                // The account's own: a user's machine is theirs, never a space's.
                return (await Machine.list({ client })).map((m) => make(m.id, m.name, [m.kind === 'own' ? 'Computer of yours' : 'Machine kept on', m.status].join(' · ')));
            default:
                return [];
        }
    });
    if (kind === 'skills') return { loading: k.loading, items: k.skills.map((s) => ({ key: thingKey(kind, s.id), kind, ref: s.id, name: s.name, detail: s.description, link: null, usedBy: [], knowledge: s })) };
    if (kind === 'memories') return { loading: k.loading, items: k.memories.map((m) => ({ key: thingKey(kind, m.id), kind, ref: m.id, name: m.name ?? '', detail: m.description, link: null, usedBy: [], knowledge: m })) };
    return { loading: read.loading, items: read.data ?? [] };
}

/** "Add from the account": the account's items of a kind not shared with this space yet, searched and ticked. */
export function AddDialog({ kind, share: here, spaceId, connections, onClose }: Pane & { kind: SpaceKind; onClose: () => void }) {
    const client = useWorkClient();
    const def = kindOf(kind);
    const [query, setQuery] = useState('');
    const [picked, setPicked] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const account = useAccountItems(kind);
    const inSpace = new Set(here.of(kind).filter((t) => kind === 'agents' || t.link).map((t) => t.ref));
    const q = query.trim().toLowerCase();
    const candidates = account.items.filter((t) => !inSpace.has(t.ref) && (!q || `${t.name} ${t.detail}`.toLowerCase().includes(q)));
    const toggle = (key: string) => setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]));
    const add = async () => {
        setBusy(true);
        // One the space's agents already use is shared with its link's own default levels.
        await addToSpace(client, spaceId, account.items.filter((t) => picked.includes(t.key)));
        onClose();
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="md"
            title={`Add ${def.noun[1]} to this space`}
            description={kind === 'agents' ? 'The account’s agents that aren’t here yet. Adding one keeps it in its other spaces too.' : `The account’s ${def.noun[1]} not shared with this space yet. Everyone here gets each one you add.`}
            mark={<Plus className="h-5 w-5" strokeWidth={1.75} />}
            testId="add-from-account"
            footer={
                <>
                    <span className="mr-auto text-[12.5px] tabular-nums text-muted-foreground">{picked.length ? `${picked.length} picked` : ''}</span>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" disabled={!picked.length || busy} onClick={() => void add()} className={BUTTON_PRIMARY}>
                        Add to this space
                    </button>
                </>
            }
        >
            <label className="relative block">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`Search the account’s ${def.noun[1]}`} className={cn(PILL_FIELD, 'pl-10')} />
            </label>
            <ul className="-mx-2 mt-3 flex max-h-[340px] flex-col overflow-y-auto pb-1 scrollbar-subtle">
                {candidates.map((t) => {
                    const on = picked.includes(t.key);
                    const usedHere = here.find(t.key)?.usedBy.map((id) => here.agent(id)?.name).filter(Boolean) as string[] | undefined;
                    return (
                        <li key={t.key}>
                            <button type="button" onClick={() => toggle(t.key)} aria-pressed={on} className={cn('flex w-full items-center gap-3 rounded-2xl px-2 py-2 text-left transition-colors', on ? 'bg-foreground/[0.06]' : 'hover:bg-foreground/[0.04]')}>
                                <span className={cn('grid h-5 w-5 shrink-0 place-items-center rounded-full ring-1 ring-inset transition-colors', on ? 'bg-foreground text-background ring-foreground' : 'ring-foreground/30')}>
                                    {on && <Check className="h-3 w-3" strokeWidth={3} />}
                                </span>
                                {kind === 'agents' ? <AgentFace agent={{ id: t.ref, name: t.name }} size={32} /> : <Lead mark={markOf(t, connections.get(t.ref))} />}
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-[14px] font-medium">{titleFor(t)}</span>
                                    <span className="block truncate text-[12.5px] text-muted-foreground">{t.detail}</span>
                                </span>
                                {usedHere?.length ? <span className="shrink-0 text-[12px] text-muted-foreground">Used by {list(usedHere)} here</span> : null}
                            </button>
                        </li>
                    );
                })}
                {!candidates.length && (
                    <li className="px-2 py-6 text-center text-[13.5px] text-muted-foreground">
                        {account.loading ? 'Reading the account’s…' : q ? 'Nothing matches.' : `Every one of the account’s ${def.noun[1]} is already here.`}
                    </li>
                )}
            </ul>
        </ShellDialog>
    );
}

/** What's made here, by the kind a space's link names it. */
const MADE_KIND = { skill: 'skills', memory: 'memories', automation: 'automations' } as const;

/** The real way to make one, by kind: made here (an agent's draft, a skill, a memory, a channel, a computer of
 *  yours, a blank automation on its canvas), else the app's own page for it, or a request to NoClick beside either.
 *  What's made here lands in the account and in this space; what NoClick makes, in the account. Code, websites,
 *  databases and files have no page of the app's to make one by hand: NoClick makes them. */
export function CreateDialog(pane: Pane & { kind: SpaceKind; onClose: () => void }) {
    const client = useWorkClient();
    const nav = useWorkNav();
    const { ask, openPage } = useWork();
    const canvas = useAutomationCanvas();
    // Only the account makes one of its own: a person in a space they joined makes nothing in its account by hand.
    const account = useWorkViewer().type === 'account';
    const [making, setMaking] = useState(false);
    const { kind, spaceId, onClose, onAt } = pane;
    const def = kindOf(kind);
    const space = pane.share.spaceName || 'this';
    useEffect(() => {
        if (kind === 'agents') {
            onClose();
            nav.newAgent();
        }
    }, [kind, nav, onClose]);
    if (kind === 'agents') return null;
    /** Shares what was made with this space (home shares it with no one: it's the account's, and listed there as all
     *  of them are), then opens it: an automation on its canvas where one opens, anything else on its page here. */
    const sharedHere = async (made: { kind: keyof typeof MADE_KIND; id: string; name?: string }) => {
        if (!pane.share.home) {
            try {
                await share(client, spaceId, made.kind, made.id);
                readSpaceAgain(spaceId);
            } catch (error) {
                toast.error('Made, but not shared with this space', { description: error instanceof Error ? error.message : String(error) });
            }
        }
        const k = MADE_KIND[made.kind];
        if (made.kind === 'automation' && canvas) canvas({ id: made.id, name: made.name ?? '' });
        else onAt({ kind: k, item: thingKey(k, made.id) });
    };
    const closed = (made: { kind: 'skill' | 'memory'; id: string } | undefined) => {
        onClose();
        if (made) void sharedHere(made);
    };
    if (kind === 'skills') return <NewSkillDialog onClose={closed} />;
    if (kind === 'memories') return <NewMemoryDialog onClose={closed} />;
    if (kind === 'channels') return <NewChannelDialog {...pane} />;
    if (kind === 'machines') return <AddMachine onDone={() => onClose()} />;
    const WAYS: Partial<Record<SpaceKind, { about: string; manual?: { label: string; run: () => void | Promise<void> }; note?: string; ask: string }>> = {
        connections: {
            about: pane.share.home ? 'A new sign-in for the account. Connect it in Connections and it shows here.' : 'A new sign-in for the account. Connect it in Connections, then add it here so everyone in this space gets it.',
            manual: openPage && { label: 'Open Connections', run: () => openPage('connections') },
            ask: pane.share.home ? 'Connect an account for my agents.' : `Connect an account for the ${space} space’s agents.`,
        },
        code: { about: 'NoClick makes a repository for the account; share it here and its agents check it out on their machines.', ask: `Make a repository for the ${space} space.` },
        automations: {
            about: 'Build it yourself on a blank canvas, or describe it and NoClick builds it: what starts it, the steps it takes and where it reports.',
            // The Automations page's New: a blank one of the account's, here shared with this space as it's made.
            manual: account
                ? {
                      label: 'Open a blank canvas',
                      run: async () => {
                          const made = await Workflow.create(null, { client });
                          await sharedHere({ kind: 'automation', id: made.id, name: made.name });
                      },
                  }
                : undefined,
            note: 'A blank one is shared with everyone here as it’s made. One NoClick builds lands in the account; add it here once it’s made.',
            ask: `Build an automation for the ${space} space.`,
        },
        websites: { about: 'NoClick builds a site from what you describe and publishes it at its own address.', ask: `Build a small website for the ${space} space and publish it.` },
        databases: { about: 'A database the account owns, which agents here query through their tools.', ask: `Make a database for the ${space} space’s agents.` },
        files: { about: 'A bucket of files the account owns, shared with this space.', ask: `Make a shared folder of files for the ${space} space.` },
        numbers: {
            about: 'A number your agents answer calls and texts on, at the carrier’s price.',
            manual: openPage && { label: 'Buy a number', run: () => openPage('resources', { ...resourceAddress('numbers', { manual: true }) }) },
            ask: `Get a number the ${space} space’s agents can answer calls and texts on.`,
        },
        email: {
            about: 'An address on one of your domains: mail to it reaches the agent that answers it.',
            manual: openPage && { label: 'New address', run: () => openPage('resources', { ...resourceAddress('email', { manual: true }) }) },
            ask: `Set up an email address for the ${space} space’s agents.`,
        },
    };
    const way = WAYS[kind]!;
    const byHand = async (manual: NonNullable<typeof way.manual>) => {
        setMaking(true);
        try {
            await manual.run();
            onClose();
        } catch (error) {
            setMaking(false);
            toast.error(`Couldn’t make the ${def.noun[0]}`, { description: error instanceof Error ? error.message : String(error) });
        }
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title={def.make}
            description={way.about}
            mark={<def.icon className="h-5 w-5" strokeWidth={1.75} />}
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    {way.manual && (
                        <button type="button" disabled={making} onClick={() => void byHand(way.manual!)} className={BUTTON_SECONDARY}>
                            {way.manual.label}
                        </button>
                    )}
                    {ask && (
                        <button
                            type="button"
                            onClick={() => {
                                onClose();
                                ask(way.ask);
                            }}
                            className={BUTTON_PRIMARY}
                        >
                            Ask NoClick
                        </button>
                    )}
                </>
            }
        >
            <p className="pb-1 text-[13px] leading-relaxed text-muted-foreground">
                {pane.share.home ? 'It lands in the account and shows here once it’s made.' : way.manual && way.note ? way.note : 'It lands in the account; add it to this space from here once it’s made.'}
            </p>
        </ShellDialog>
    );
}

function NewChannelDialog({ spaceId, share: here, onClose }: Pane & { onClose: () => void }) {
    const client = useWorkClient();
    const nav = useWorkNav();
    const [name, setName] = useState('');
    const [topic, setTopic] = useState('');
    const [busy, setBusy] = useState(false);
    const taken = here.of('channels').some((c) => c.name === name);
    const create = async () => {
        setBusy(true);
        try {
            const made = await Channel.create(name, { client, workspace: spaceId, topic: topic.trim() || undefined, mode: 'all' });
            readSpaceAgain(spaceId);
            onClose();
            toast(`#${name} is in this space`, { action: { label: 'Open', onClick: () => nav.openChannel(made.id) }, description: 'Add agents by @-mentioning them in it.' });
        } catch (error) {
            toast.error('Couldn’t make the channel', { description: error instanceof Error ? error.message : String(error) });
            setBusy(false);
        }
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title="New channel in this space"
            description="Where people and agents talk about one thing."
            mark={<Hash className="h-5 w-5" strokeWidth={1.75} />}
            onSubmit={(e) => {
                e.preventDefault();
                if (name && !taken && !busy) void create();
            }}
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="submit" disabled={!name || taken || busy} className={BUTTON_PRIMARY}>
                        Create channel
                    </button>
                </>
            }
        >
            <div className="flex flex-col gap-4 pb-1">
                <label>
                    <span className={FIELD_LABEL}>Name</span>
                    <input value={name} onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))} placeholder="billing" className={PILL_FIELD} />
                    {taken && <span className="mt-1.5 block text-[12.5px] text-red-600 dark:text-red-400">#{name} is already in this space.</span>}
                </label>
                <label>
                    <span className={FIELD_LABEL}>Topic</span>
                    <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="What it’s for" className={PILL_FIELD} />
                </label>
            </div>
        </ShellDialog>
    );
}

/** Delete is account-wide: it says what the platform will do and names every agent that loses it before anything goes. */
export function DeleteDialog({ t, spaceId, share: here, onAt, onClose }: Pane & { t: Thing; onClose: () => void }) {
    const client = useWorkClient();
    const [impact, setImpact] = useState<Awaited<ReturnType<typeof previewDelete>>>(null);
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        let live = true;
        previewDelete(client, t)
            .then((found) => live && setImpact(found))
            .catch((error: unknown) => console.warn('[resources] the delete preview failed:', error));
        return () => {
            live = false;
        };
    }, [client, t]);
    // A secret's agents are named from the preview, which takes it off each of them first (here or not).
    const agents = t.kind === 'agents' || t.kind === 'secrets' ? [] : t.usedBy.map((id) => here.agent(id)).filter((a): a is NonNullable<typeof a> => !!a);
    const removes = removedForGood(t);
    const confirm = async () => {
        setBusy(true);
        const gone = await deleteThing(client, spaceId, t);
        onClose();
        if (gone) onAt({ kind: t.kind });
    };
    const description =
        t.kind === 'secrets'
            ? 'It comes off every agent that holds it, then it’s deleted for good. A sandbox already running keeps it until it stops.'
            : impact?.deletes || (impact?.reversible === false ? 'It’s gone for good, from every space and every agent.' : 'It goes to the account’s trash for 30 days, out of every space and every agent.');
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            tone="danger"
            title={`${removes ? 'Remove' : 'Delete'} ${titleFor(t)}?`}
            description={description}
            mark={<Trash2 className="h-5 w-5" strokeWidth={1.75} />}
            testId="delete-confirm"
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" disabled={busy} onClick={() => void confirm()} className={BUTTON_DANGER}>
                        {removes ? 'Remove' : impact?.reversible === false ? 'Delete for good' : 'Move to the trash'}
                    </button>
                </>
            }
        >
            <div className="flex flex-col gap-3 pb-1 text-[13.5px]">
                {agents.length > 0 && (
                    <div>
                        <p className="mb-1.5 text-[12.5px] text-muted-foreground">Used here by</p>
                        <ul className="flex flex-col gap-1.5">
                            {agents.map((a) => (
                                <li key={a.id} className="flex items-center gap-2.5">
                                    <AgentFace agent={a} size={20} />
                                    <span>
                                        <span className="font-medium">{a.name}</span>
                                        {a.elsewhere.length > 0 && <span className="text-muted-foreground"> · also in {list(a.elsewhere)}</span>}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
                {impact?.dependsOnIt.length ? (
                    <div>
                        <p className="mb-1.5 text-[12.5px] text-muted-foreground">{removes ? 'Loses it' : 'Depends on it'}</p>
                        {/* The platform says each in a sentence of its own ("The agent Infra uses it …"). */}
                        {impact.dependsOnIt.some((d) => d.includes(' ')) ? (
                            <ul className="flex flex-col gap-1">
                                {impact.dependsOnIt.map((d) => (
                                    <li key={d}>{d}</li>
                                ))}
                            </ul>
                        ) : (
                            <p>{list(impact.dependsOnIt)}</p>
                        )}
                    </div>
                ) : null}
                {impact?.dataLost.length ? (
                    <div>
                        <p className="mb-1.5 text-[12.5px] text-muted-foreground">Data lost</p>
                        <p>{list(impact.dataLost)}</p>
                    </div>
                ) : null}
                {t.link && <p className="text-muted-foreground">To keep it elsewhere, remove it from this space instead.</p>}
            </div>
        </ShellDialog>
    );
}

/** Home's way to give one to a space: an agent joins it (staying in the others it's in), anything else is shared with
 *  everyone in it. A space that has it already says so. */
export function ShareDialog({ t, share: here, onClose }: Pane & { t: Thing; onClose: () => void }) {
    const client = useWorkClient();
    const [busy, setBusy] = useState(false);
    const agent = t.kind === 'agents';
    const give = async (space: SpaceShare['spaces'][number]) => {
        setBusy(true);
        await addToSpace(client, space.id, [t], space.name);
        onClose();
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            title={agent ? `Add ${titleFor(t)} to a space` : `Share ${titleFor(t)} with a space`}
            description={agent ? 'It works in the space’s channels, with the people there, and stays in the spaces it’s in.' : 'Everyone in the space gets it, and anyone who joins later. The agents that use it keep it.'}
            mark={<UsersRound className="h-5 w-5" strokeWidth={1.75} />}
            testId="share-with-space"
            footer={
                <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                    Cancel
                </button>
            }
        >
            {here.spaces.length ? (
                <ul className="-mx-2 flex max-h-[340px] flex-col overflow-y-auto pb-1 scrollbar-subtle">
                    {here.spaces.map((space) => (
                        <SpaceChoice key={space.id} space={space} t={t} busy={busy} onPick={() => void give(space)} />
                    ))}
                </ul>
            ) : (
                <p className="pb-1 text-[13.5px] leading-relaxed text-muted-foreground">You have no space yet. Make one from the rail, and everyone you invite to it gets what you share.</p>
            )}
        </ShellDialog>
    );
}

function SpaceChoice({ space, t, busy, onPick }: { space: SpaceShare['spaces'][number]; t: Thing; busy: boolean; onPick: () => void }) {
    const agent = t.kind === 'agents';
    const links = useSpaceLinks(agent ? null : space.id);
    const has = agent ? space.agentIds.includes(t.ref) : !!links.data?.some((l) => l.kind === LINK_KIND[t.kind] && l.ref === t.ref);
    // Unread, the space itself refuses one it has.
    const reading = !agent && !links.data && !links.error;
    return (
        <li>
            <button
                type="button"
                disabled={busy || has || reading}
                onClick={onPick}
                className="flex w-full items-center gap-3 rounded-full px-2 py-1.5 text-left transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none"
            >
                <WorkspaceTile workspace={space} size={28} />
                <span className={cn('min-w-0 flex-1 truncate text-[14px] font-medium', has && 'text-muted-foreground')}>{space.name}</span>
                {has && <span className="shrink-0 pr-2 text-[12.5px] text-muted-foreground">{agent ? 'In it already' : 'Shared already'}</span>}
                {!!links.error && <span className="shrink-0 pr-2 text-[12.5px] text-muted-foreground">Couldn’t check what it has</span>}
            </button>
        </li>
    );
}

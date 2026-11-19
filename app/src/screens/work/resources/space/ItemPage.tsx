// One item's own page in a space's Resources tab, the anatomy of the app's account and resource pages: the way back,
// its name, its facts, then sections. Links go where things live: an agent to its profile, a channel to the channel,
// a machine to its machine page. A skill or memory is its own page, with the space's menu beside the way back. A
// connection or a secret says where a move carried it from, and its Remove ends its access everywhere. Home's pages say
// nothing of sharing: nobody else is in a home.
import { useState, type ReactNode } from 'react';
import { ArrowUpRight, Hash, Server, Trash2 } from 'lucide-react';
import { Channel, type Connection } from 'noclick';
import { installedAs, installedFacts, installedLine } from '@/screens/resources/secrets';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { Section, Surface } from '@/screens/resources/ui';
import { movedFacts, type MovedFrom } from '@/lib/movedFrom';
import { cn } from '@/ui/utils';
import { AgentRing } from '../../agents/AgentRing';
import { useAgentFaces, useWorkV1 } from '../../agents/reads';
import { useWorkClient } from '../../client';
import { useWorkNav } from '../../nav';
import { PageHead } from '@/ui/PageHead';
import { KnowledgePage } from '../knowledge/KnowledgePage';
import { AgentFace } from '../knowledge/parts';
import { MachineBody, placeKind } from '../machines';
import { addToSpace, removedForGood, shareable, titleFor } from './actions';
import { appName, kindOf, levelWords, thingKey, type Thing } from './data';
import { ReconnectButton, sharedLine } from './KindPage';
import { Crumbs, Facts, LevelMenu, List, markOf, NameInput, PageRow, ThingMenu } from './parts';
import { ACCOUNT_KIND, type Pane } from './pane';

export function ItemPage(props: Pane & { t: Thing }) {
    const { t, onAt } = props;
    if (t.kind === 'skills' || t.kind === 'memories') {
        return (
            <>
                <div className="px-5 sm:px-8">
                    <Crumbs onAt={onAt} kind={t.kind} end={<ThingMenu pane={props} t={t} onPage label={props.share.home ? undefined : 'In this space'} className="bg-foreground/[0.05]" />} />
                </div>
                <KnowledgePage
                    id={t.ref}
                    now={props.now}
                    onOpen={(id) => {
                        const found = props.share.find(thingKey('skills', id)) ?? props.share.find(thingKey('memories', id));
                        onAt({ kind: found?.kind ?? t.kind, item: found?.key ?? thingKey(t.kind, id) });
                    }}
                    onTrashed={() => onAt({ kind: t.kind })}
                />
            </>
        );
    }
    const body = (() => {
        switch (t.kind) {
            case 'connections':
                return <ConnectionBody {...props} />;
            case 'secrets':
                return <SecretBody {...props} />;
            case 'channels':
                return <ChannelBody {...props} />;
            case 'machines':
                return (
                    <>
                        {t.place ? <MachineBody place={t.place} now={props.now} /> : <p className="mt-6 text-[14px] text-muted-foreground">{t.machine?.state === 'running' ? 'It’s running.' : 'It isn’t up now.'}</p>}
                        {!props.share.home && (t.link || shareable(t)) && <InSpaceSection pane={props} t={t} />}
                    </>
                );
            default:
                return <ResourceBody {...props} />;
        }
    })();
    return (
        <PageFrame {...props} subtitle={pageSubtitle(t, props)} primary={<PagePrimary {...props} />}>
            {body}
        </PageFrame>
    );
}

function pageSubtitle(t: Thing, pane: Pane): string {
    switch (t.kind) {
        case 'connections': {
            const c = pane.connections.get(t.ref);
            return ['Connection', c?.account ?? (c ? appName(c.integration) : null)].filter(Boolean).join(' · ');
        }
        case 'channels':
            return 'Channel';
        case 'secrets':
            return ['Secret', t.secret ? installedLine(installedAs(t.secret)) : null].filter(Boolean).join(' · ');
        case 'machines':
            return t.place ? placeKind(t.place) : 'Machine';
        default:
            return `${kindOf(t.kind).noun[0].charAt(0).toUpperCase()}${kindOf(t.kind).noun[0].slice(1)} · ${sharedLine(t)}`;
    }
}

function PagePrimary({ t, accountPage, ask }: Pane & { t: Thing }) {
    const nav = useWorkNav();
    if (removedForGood(t))
        return (
            <button type="button" onClick={() => ask({ kind: 'delete', key: t.key })} className={cn(BUTTON_SECONDARY, 'hover:text-red-600 dark:hover:text-red-400')}>
                <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                Remove
            </button>
        );
    if (t.kind === 'channels')
        return (
            <button type="button" onClick={() => nav.openChannel(t.ref)} className={BUTTON_PRIMARY}>
                <Hash className="h-4 w-4" strokeWidth={1.9} />
                Open channel
            </button>
        );
    if (t.kind === 'machines' && t.machine?.agentId)
        return (
            <button type="button" onClick={() => nav.openMachine(t.machine!.agentId!)} className={BUTTON_PRIMARY}>
                <Server className="h-4 w-4" strokeWidth={1.9} />
                Open machine
            </button>
        );
    const kind = ACCOUNT_KIND[t.kind];
    if (kind && t.kind !== 'machines' && accountPage)
        return (
            <button type="button" onClick={() => accountPage(kind, t.ref)} className={BUTTON_SECONDARY}>
                Open in Resources
                <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={1.9} />
            </button>
        );
    return null;
}

function PageFrame({ children, subtitle, primary, ...pane }: Pane & { t: Thing; subtitle: string; primary?: ReactNode; children: ReactNode }) {
    const client = useWorkClient();
    const { t, onAt } = pane;
    const [renaming, setRenaming] = useState(false);
    return (
        <div data-testid="item-page">
            <Crumbs onAt={onAt} kind={t.kind} />
            <PageHead
                lead={<span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-foreground/[0.06]">{markOf(t, pane.connections.get(t.ref), 'h-[22px] w-[22px]')}</span>}
                title={titleFor(t)}
                editor={
                    renaming ? (
                        <NameInput
                            big
                            value={t.name}
                            prefix={t.kind === 'channels' ? '#' : undefined}
                            onDone={(next) => {
                                setRenaming(false);
                                if (next && next !== t.name) void pane.rename(client, t, next);
                            }}
                        />
                    ) : undefined
                }
                line={subtitle}
                actions={
                    <>
                        {primary}
                        <ThingMenu pane={pane} t={t} onPage onRename={() => setRenaming(true)} className="h-9 w-9 bg-foreground/[0.05]" />
                    </>
                }
            />
            {children}
        </div>
    );
}

/** Its agents here, each a row to its profile with its line now. */
function UsedBySection({ pane, t, title = 'Used by', empty }: { pane: Pane; t: Thing; title?: string; empty: string }) {
    const nav = useWorkNav();
    const faces = useAgentFaces();
    const agents = t.usedBy.map((id) => pane.share.agent(id)).filter((a): a is NonNullable<typeof a> => !!a);
    return (
        <Section title={title} meta={agents.length || undefined}>
            {agents.length ? (
                <List>
                    {agents.map((a) => (
                        <PageRow
                            key={a.id}
                            lead={<AgentRing member={faces.get(a.id) ?? { id: a.id, kind: 'agent', name: a.name }} status={a.status} size={28} />}
                            title={a.name}
                            sub={a.line}
                            onOpen={() => nav.openProfile(a.id)}
                            hint="Profile"
                        />
                    ))}
                </List>
            ) : (
                <p className="text-[14px] text-muted-foreground">{empty}</p>
            )}
        </Section>
    );
}

/** Whether it's shared with the space, what members and guests get, and a way to share one only agents use. */
function InSpaceSection({ pane, t }: { pane: Pane; t: Thing }) {
    const client = useWorkClient();
    const link = t.link;
    return (
        <Section title="In this space">
            {link ? (
                <Facts
                    rows={[
                        ['Shared', 'With everyone in this space, and anyone who joins'],
                        ['People here get', <LevelMenu key="members" spaceId={pane.spaceId} link={link} who="members" />],
                        ['Guests get', <LevelMenu key="guests" spaceId={pane.spaceId} link={link} who="guests" />],
                        ...((link.addedBy?.name ? [['Shared by', link.addedBy.name]] : []) as [string, string][]),
                    ]}
                />
            ) : (
                <Surface className="flex flex-wrap items-center gap-x-4 gap-y-3 px-4 py-3.5 sm:px-5">
                    <p className="min-w-0 flex-1 text-[14px] leading-snug text-foreground/90">
                        {t.kind === 'machines' ? 'People here don’t see it, and only you put agents on it, until you share it with the space. Its shell stays yours.' : 'Only its agents use it. People here don’t get it until you share it with the space.'}
                    </p>
                    {shareable(t) && (
                        <button type="button" onClick={() => void addToSpace(client, pane.spaceId, [t])} className={BUTTON_SECONDARY}>
                            Share with this space
                        </button>
                    )}
                </Surface>
            )}
        </Section>
    );
}

function connectionState(c: Connection | undefined): { dot: string; words: string; note: string } {
    if (!c) return { dot: 'bg-muted-foreground/50', words: 'Not read', note: 'Its account couldn’t be read.' };
    if (c.status === 'disconnected') return { dot: 'bg-red-500', words: `${appName(c.integration)} turned it down`, note: 'Its agents’ tools from it stop until it’s reconnected.' };
    if (c.status === 'pending') return { dot: 'bg-muted-foreground/50', words: 'Waiting to be connected', note: 'Its sign-in hasn’t finished.' };
    return { dot: 'bg-emerald-500', words: 'Working', note: c.account ? `Signed in as ${c.account}.` : 'Connected.' };
}

function ConnectionBody(props: Pane & { t: Thing }) {
    const { t, connections } = props;
    const c = connections.get(t.ref);
    const state = connectionState(c);
    const holders = (c?.usedBy ?? []).filter((h) => !t.usedBy.includes(h.id));
    return (
        <>
            <Section title="Connection">
                <Surface className={cn('px-4 py-4 sm:px-5', c?.status === 'disconnected' && 'border-red-500/25 dark:border-red-500/25')}>
                    <p className="flex items-center gap-2.5 text-[14px] font-medium">
                        <span className={cn('h-2 w-2 rounded-full', state.dot)} />
                        {state.words}
                    </p>
                    <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{state.note}</p>
                    {c?.status === 'disconnected' && c.connectUrl && (
                        <div className="mt-4">
                            <ReconnectButton url={c.connectUrl} />
                        </div>
                    )}
                </Surface>
            </Section>
            <UsedBySection pane={props} t={t} empty="No agent here uses it yet. Attach it on an agent’s profile." />
            {t.movedFrom && <MovedSection moved={t.movedFrom} what="its credential" />}
            {!props.share.home && <InSpaceSection pane={props} t={t} />}
            <Section title={props.share.home ? 'Who has it' : 'Shared with'}>
                <Facts
                    rows={[
                        ['Owner', c?.userId ? 'One of your users' : 'The account'],
                        ['Elsewhere', holders.length ? holders.map((h) => h.name).join(', ') : 'Nothing else holds it'],
                        ...((props.share.home ? [] : [['People here', t.link ? levelWords(t.link.kind, t.link.membersLevel) : 'No one: only its agents use it']]) as [string, string][]),
                    ]}
                />
            </Section>
        </>
    );
}

/** Where a move carried it from: the computer, its folder there, and when, with what Remove takes away. */
function MovedSection({ moved, what }: { moved: MovedFrom; what: string }) {
    return (
        <Section title="Moved here">
            <Facts rows={movedFacts(moved)} />
            <p className="mt-3 text-[12.5px] text-muted-foreground">It came over when an agent moved from this computer. Remove it to take {what} away from every agent here and elsewhere.</p>
        </Section>
    );
}

/** A secret by name: where an agent holding it finds it (never its value), the agents here and elsewhere that hold it,
 *  and where a move carried it from. */
function SecretBody(props: Pane & { t: Thing }) {
    const { t } = props;
    const nav = useWorkNav();
    const faces = useAgentFaces();
    const sec = t.secret;
    if (!sec) return null;
    const here = new Set(t.usedBy);
    // Named as Work names them (the account's coordinator is NoClick).
    const elsewhere = sec.agents.filter((a) => !here.has(a.id)).map((a) => ({ id: a.id, name: faces.get(a.id)?.name ?? a.name }));
    return (
        <>
            <Section title="Where it is">
                <Facts rows={[...installedFacts(installedAs(sec)), ['Value', 'Never shown here']]} />
            </Section>
            <UsedBySection pane={props} t={t} title="Held by" empty="No agent here holds it." />
            {elsewhere.length > 0 && (
                <Section title="Also held by" meta={elsewhere.length}>
                    <List>
                        {elsewhere.map((a) => (
                            <PageRow
                                key={a.id}
                                lead={<AgentFace agent={a} size={28} />}
                                title={a.name}
                                sub={props.share.spacesOf(a.id).length ? `In ${props.share.spacesOf(a.id).join(', ')}` : 'In no space'}
                                onOpen={() => nav.openProfile(a.id)}
                                hint="Profile"
                            />
                        ))}
                    </List>
                </Section>
            )}
            {t.movedFrom && <MovedSection moved={t.movedFrom} what="it" />}
        </>
    );
}

function ChannelBody(props: Pane & { t: Thing }) {
    const { t } = props;
    const nav = useWorkNav();
    const channel = useWorkV1(`work:channel/${t.ref}`, (client) => Channel.get(t.ref, { client }));
    const c = channel.data;
    const agents = (c?.members ?? []).filter((m) => m.type === 'agent' && m.agentId);
    const people = (c?.members ?? []).filter((m) => m.type === 'user');
    return (
        <>
            <Section title="Facts">
                <Facts
                    rows={[
                        ['Topic', c?.topic || 'No topic yet'],
                        ['Unread', c ? (c.unreadCount ? `${c.unreadCount} new` : 'All read') : '—'],
                        ['Members', c ? `${people.length + 1} ${people.length ? 'people' : 'person'}, ${agents.length} ${agents.length === 1 ? 'agent' : 'agents'}` : '—'],
                    ]}
                />
            </Section>
            <Section title="Agents in it" meta={agents.length || undefined}>
                {agents.length ? (
                    <List>
                        {agents.map((m) => {
                            const here = props.share.agent(m.agentId!);
                            return (
                                <PageRow
                                    key={m.id}
                                    lead={<AgentFace agent={{ id: m.agentId!, name: here?.name ?? m.agentId! }} size={28} />}
                                    title={here?.name ?? 'An agent'}
                                    sub={here?.line ?? ''}
                                    onOpen={() => nav.openProfile(m.agentId!)}
                                    hint="Profile"
                                />
                            );
                        })}
                    </List>
                ) : (
                    <p className="text-[14px] text-muted-foreground">No agent yet. @-mention one in the channel to add it.</p>
                )}
            </Section>
        </>
    );
}

function ResourceBody(props: Pane & { t: Thing }) {
    const { t } = props;
    const answers = t.kind === 'numbers' || t.kind === 'email';
    return (
        <>
            <Section title="Facts">
                <Facts
                    rows={[
                        ['Owner', 'The account'],
                        ['Here', answers ? 'Answered by agents in this space' : sharedLine(t)],
                    ]}
                />
            </Section>
            <UsedBySection pane={props} t={t} title={answers ? 'Answered by' : 'Used by'} empty={answers ? 'No agent here answers it.' : 'No agent here works with it yet.'} />
            {answers ? <p className="mt-4 text-[12.5px] text-muted-foreground">It reaches this space through the agent that answers it.</p> : <InSpaceSection pane={props} t={t} />}
        </>
    );
}

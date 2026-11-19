// One kind of what a space has, as a list: its rows (each opening its page; an agent's opens its profile), who here
// uses each, and the ways to get more (make one, or add one the account already has). Home lists every one of the
// account's, so it has nothing to add and nothing to say about sharing.
import { Plus } from 'lucide-react';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { AgentRing } from '../../agents/AgentRing';
import { HarnessMark, harnessLabel } from '../../agents/harness';
import { useAgentFaces } from '../../agents/reads';
import { useWorkNav } from '../../nav';
import { DisabledTip } from '../../tooltip';
import { PageHead } from '@/ui/PageHead';
import { ItemMark } from '../knowledge/parts';
import { useKnowledge } from '../knowledge/store';
import { AGENTS_NOT_ENABLED, placeSize, placeState, placeUp, useAgentsOnMachines } from '../machines';
import type { HarnessName } from 'noclick';
import { installedAs, installedLine } from '@/screens/resources/secrets';
import { movedLine } from '@/lib/movedFrom';
import { kindOf, levelWords, LINK_KIND, ownMachine, type SpaceKind, type Thing } from './data';
import { Group } from './Overview';
import { MovedSignIns } from './SignIns';
import { Also, Crumbs, Empty, List, Owned, plural, Row, UsedBy, type RowProps } from './parts';
import { ACCOUNT_KIND, type Pane } from './pane';

const ABOUT: Record<SpaceKind, string> = {
    agents: 'Every agent in this space, and what each is doing now.',
    machines: 'Where this space’s agents run: each agent’s one cloud sandbox, shared by everyone talking to it, a machine kept on, or a computer of yours. A machine shared with this space is one its people see, and can put its agents on where you let them.',
    skills: 'What this space’s agents follow. Each is the account’s, so a change reaches every agent that uses it, here and elsewhere.',
    memories: 'What this space’s agents read, and add to where you let them. Each agent also keeps its own.',
    connections: 'Accounts shared with everyone here, and the ones only an agent uses.',
    secrets: 'The keys and tokens this space’s agents hold, by name and where each is installed, and which came over when an agent moved from a computer. A value is never shown.',
    channels: 'Where this space’s people and agents talk.',
    code: 'Repositories shared with this space or checked out on its agents’ machines.',
    websites: 'Sites shared with this space, or that its agents work on.',
    databases: 'Databases shared with this space, or that its agents query.',
    files: 'Files shared with this space, or that its agents keep.',
    numbers: 'Phone numbers this space’s agents answer.',
    email: 'Email addresses this space’s agents answer.',
};

const HOME_ABOUT: Partial<Record<SpaceKind, string>> = {
    agents: 'Every agent of the account, where each is, and what it’s doing now.',
    machines: 'Where your agents run: each agent’s one cloud sandbox, shared by everyone talking to it, a machine kept on, or a computer of yours.',
    skills: 'Every skill of the account. A change reaches every agent that uses it, here and in your spaces.',
    memories: 'Every memory of the account, and each agent’s own.',
    connections: 'Every sign-in the account holds, and which of your agents use each.',
    secrets: 'Every key and token of the account, by name and where each is installed, and which came over when an agent moved from a computer. A value is never shown.',
};

/** Its line: shared with everyone here (at what level), or only its agents'. */
export function sharedLine(t: Thing): string {
    if (!t.link) return 'Only its agents';
    return `Shared with everyone here · ${levelWords(t.link.kind, t.link.membersLevel).toLowerCase()}`;
}

/** The agents outside this space that use it too: their spaces, so a change made here reaches them. */
function useAlsoIn(pane: Pane) {
    const k = useKnowledge();
    return (t: Thing): string[] => {
        if (!t.knowledge) return [];
        const here = new Set(pane.share.agents.map((a) => a.id));
        const outside = k.usersOf(t.knowledge).filter((u) => !here.has(u.agent.id));
        return outside.flatMap((u) => pane.share.spacesOf(u.agent.id)).filter((n) => n !== pane.share.spaceName);
    };
}

export function KindPage(pane: Pane & { kind: SpaceKind }) {
    const { kind, share, onAt, ask } = pane;
    const def = kindOf(kind);
    const things = share.of(kind);
    // Home already lists all of the account's.
    const canAdd = !share.home && (kind === 'agents' || !!LINK_KIND[kind]);
    // A machine here is a computer of yours, which can't be added while agents don't run on machines.
    const enabled = useAgentsOnMachines();
    const refusal = kind === 'machines' && enabled === false ? AGENTS_NOT_ENABLED : null;
    return (
        <>
            <Crumbs onAt={onAt} />
            <PageHead
                className="mb-6"
                title={def.label}
                line={(share.home && HOME_ABOUT[kind]) || ABOUT[kind]}
                actions={
                    (canAdd || def.make) && (
                        <>
                            {canAdd && (
                                <button type="button" onClick={() => ask({ kind: 'add', of: kind })} className={BUTTON_SECONDARY}>
                                    Add from the account
                                </button>
                            )}
                            {def.make && (
                                <span className="flex flex-col items-start gap-1 @2xl:items-end">
                                    <DisabledTip label={refusal} disabled={!!refusal}>
                                        <button type="button" disabled={!!refusal} onClick={() => ask({ kind: 'create', of: kind })} className={BUTTON_PRIMARY}>
                                            <Plus className="h-4 w-4" strokeWidth={2} />
                                            {def.make}
                                        </button>
                                    </DisabledTip>
                                    {refusal && (
                                        <span className="max-w-[280px] text-[12.5px] text-muted-foreground @2xl:text-right" data-testid="agents-not-enabled">
                                            {refusal}
                                        </span>
                                    )}
                                </span>
                            )}
                        </>
                    )
                }
            />
            {things.length ? <KindBody {...pane} kind={kind} things={things} /> : <Empty kind={kind} home={share.home} />}
        </>
    );
}

function KindBody(pane: Pane & { kind: SpaceKind; things: Thing[] }) {
    const { kind, things, share } = pane;
    const nav = useWorkNav();
    const faces = useAgentFaces();
    const k = useKnowledge();
    const alsoIn = useAlsoIn(pane);
    const accountList = ACCOUNT_KIND[kind];
    const { accountPage } = pane;
    const owned = (what: string, lead?: string) => (accountList && accountPage ? <Owned what={what} lead={lead} onOpen={() => accountPage(accountList)} /> : null);
    const row = (t: Thing, props: Partial<RowProps> = {}) => <Row key={t.key} pane={pane} t={t} {...props} />;
    switch (kind) {
        case 'agents': {
            const slot = share.agents.some((a) => a.status === 'needs') ? 'w-[76px]' : undefined;
            return (
                <List>
                    {things.map((t) => {
                        const a = share.agent(t.ref)!;
                        return row(t, {
                            lead: <AgentRing member={faces.get(a.id) ?? { id: a.id, kind: 'agent', name: a.name }} status={a.status} size={32} />,
                            badge: <Also names={a.elsewhere} lead={share.home ? 'In' : undefined} />,
                            sub: a.line,
                            strong: a.status === 'needs',
                            slot,
                            cols: (
                                <span className="hidden w-[200px] shrink-0 items-center gap-1.5 truncate text-[12.5px] text-muted-foreground @2xl:flex">
                                    {a.harness && <HarnessMark harness={a.harness as HarnessName} className="h-3.5 w-3.5" />}
                                    <span className="truncate">{[a.harness ? harnessLabel(a.harness as HarnessName) : null, a.model].filter(Boolean).join(' · ')}</span>
                                </span>
                            ),
                            trailing:
                                a.status === 'needs' ? (
                                    <button
                                        type="button"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            nav.openAgent(a.id);
                                        }}
                                        className="inline-flex h-7 shrink-0 items-center rounded-full bg-foreground px-3 text-[12.5px] font-medium text-background transition-colors hover:bg-foreground/90"
                                    >
                                        Answer
                                    </button>
                                ) : null,
                        });
                    })}
                </List>
            );
        }
        case 'machines': {
            const sandboxes = things.filter((t) => t.machine?.kind === 'sandbox');
            const keptOn = things.filter((t) => t.machine?.kind === 'machine' && !ownMachine(t));
            const own = things.filter(ownMachine);
            const machineRow = (t: Thing) =>
                row(t, {
                    sub: (
                        <span className="flex min-w-0 items-center gap-2">
                            <span className={(t.place ? placeUp(t.place) : t.machine?.state === 'running') ? 'h-2 w-2 shrink-0 rounded-full bg-emerald-500' : 'h-2 w-2 shrink-0 rounded-full ring-[1.5px] ring-inset ring-foreground/40'} />
                            <span className="truncate">{[t.place ? placeState(t.place, pane.now) : t.machine?.state, t.place ? placeSize(t.place) : null, t.link ? `shared here · ${levelWords(t.link.kind, t.link.membersLevel).toLowerCase()}` : null].filter(Boolean).join(' · ')}</span>
                        </span>
                    ),
                    cols: <UsedBy pane={pane} agentIds={t.usedBy} note="runs here" />,
                });
            const group = (title: string, meta: string, rows: Thing[], none: string) => (
                <Group title={title} meta={meta}>
                    {rows.length ? <List>{rows.map(machineRow)}</List> : <p className="px-1 text-[13px] text-muted-foreground">{none}</p>}
                </Group>
            );
            return (
                <div className="flex flex-col gap-9">
                    {group('Cloud sandboxes', `${share.up.sandboxes} of ${sandboxes.length} up`, sandboxes, 'None here.')}
                    {group('Kept on', `${share.up.keptOn} up`, keptOn, share.home ? 'No machine is kept on.' : 'No machine is kept on for this space’s agents.')}
                    {group('Your own computers', `${share.up.own} online`, own, 'None of yours here.')}
                </div>
            );
        }
        case 'skills':
        case 'memories': {
            const knowRow = (t: Thing) =>
                row(t, {
                    lead: <ItemMark kind={kind === 'skills' ? 'skill' : 'memory'} />,
                    badge: <Also names={alsoIn(t)} />,
                    sub: [t.knowledge?.description, t.link ? 'shared with everyone here' : null].filter(Boolean).join(' · '),
                    cols: <UsedBy pane={pane} agentIds={t.usedBy} />,
                });
            const shared = things.filter((t) => !(t.knowledge?.kind === 'memory' && t.knowledge.agentId));
            const own = things.filter((t) => t.knowledge?.kind === 'memory' && t.knowledge.agentId);
            const here = new Set(things.map((t) => t.ref));
            const unused = (kind === 'skills' ? k.skills : k.memories).filter((i) => !here.has(i.id)).length;
            return (
                <>
                    {own.length ? (
                        <div className="flex flex-col gap-9">
                            <Group title={share.home ? 'For any agent' : 'Shared'} meta={shared.length}>
                                {shared.length ? <List>{shared.map(knowRow)}</List> : <p className="px-1 text-[13px] text-muted-foreground">{share.home ? 'None yet.' : 'None shared here yet.'}</p>}
                            </Group>
                            <Group title="Each agent’s own" meta={own.length}>
                                <List>{own.map(knowRow)}</List>
                            </Group>
                        </div>
                    ) : (
                        <List>{shared.map(knowRow)}</List>
                    )}
                    {owned(
                        `all of the account’s ${kind}`,
                        unused > 0 ? `The account has ${plural(unused, [`more ${kindOf(kind).noun[0]}`, `more ${kindOf(kind).noun[1]}`])} no agent here uses.` : undefined
                    )}
                </>
            );
        }
        case 'connections': {
            const broken = (t: Thing) => pane.connections.get(t.ref)?.status === 'disconnected';
            const slot = things.some(broken) ? 'w-[104px]' : undefined;
            return (
                <>
                    <MovedSignIns pane={pane} />
                    <List>
                        {things.map((t) => {
                            const c = pane.connections.get(t.ref);
                            return row(t, {
                                connection: c,
                                sub: broken(t) ? 'It stopped working: reconnect it' : [share.home ? null : sharedLine(t), c?.account, t.movedFrom ? movedLine(t.movedFrom) : null].filter(Boolean).join(' · '),
                                attention: broken(t),
                                slot,
                                cols: <UsedBy pane={pane} agentIds={t.usedBy} />,
                                trailing: broken(t) && c?.connectUrl ? <ReconnectButton url={c.connectUrl} /> : null,
                            });
                        })}
                    </List>
                    {!share.home && (
                        <p className="mt-4 text-[12.5px] text-muted-foreground">
                            What people here get of one shared with this space is set on its page and in{' '}
                            <button type="button" onClick={() => nav.openMembers('access')} className="text-foreground/85 underline-offset-2 hover:underline">
                                What members can reach
                            </button>
                            . The rest are agents’ own. The account keeps all of them in Connections.
                        </p>
                    )}
                </>
            );
        }
        case 'secrets':
            return (
                <>
                    <List>
                        {things.map((t) =>
                            row(t, {
                                sub: [t.secret ? installedLine(installedAs(t.secret)) : null, t.movedFrom ? movedLine(t.movedFrom) : null].filter(Boolean).join(' · '),
                                cols: <UsedBy pane={pane} agentIds={t.usedBy} />,
                            })
                        )}
                    </List>
                    {owned('all of the account’s secrets')}
                </>
            );
        case 'channels':
            return <List>{things.map((t) => row(t, { sub: 'Channel', cols: <UsedBy pane={pane} agentIds={t.usedBy} /> }))}</List>;
        default: {
            const answers = kind === 'numbers' || kind === 'email';
            return (
                <>
                    <List>
                        {things.map((t) =>
                            row(t, {
                                sub: answers ? 'Answered by its agents' : sharedLine(t),
                                cols: <UsedBy pane={pane} agentIds={t.usedBy} note={answers ? 'answers' : undefined} />,
                            })
                        )}
                    </List>
                    {owned(`all of the account’s ${kindOf(kind).noun[1]}`)}
                </>
            );
        }
    }
}

/** Opens the connection's own sign-in again, in a new tab. */
export function ReconnectButton({ url }: { url: string }) {
    return (
        <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex h-7 shrink-0 items-center rounded-full px-3 text-[12.5px] font-medium text-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.06] dark:ring-foreground/[0.14]"
        >
            Reconnect
        </a>
    );
}


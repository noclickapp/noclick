// A space's Resources at a glance: two big cards (its agents and how many work or wait on you, the machines up now),
// then a tile for every other kind with how many it has and a quiet "+" to make one where it's made here. Secrets say
// how many came over with a move from a computer. Home's has only the kinds its agents work with.
import type { ReactNode } from 'react';
import { ArrowUpRight, ChevronRight, Plus } from 'lucide-react';
import { Tile } from '@/ui/Tile';
import { DisabledTip } from '../../tooltip';
import { PageHead } from '@/ui/PageHead';
import { DISPLAY } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { AgentRing } from '../../agents/AgentRing';
import { useAgentFaces } from '../../agents/reads';
import { useWorkNav } from '../../nav';
import { AGENTS_NOT_ENABLED, isOwn, placeState, useAgentsOnMachines } from '../machines';
import { GROUPS, kindOf, type SpaceKind } from './data';
import { titleFor } from './actions';
import { enterOpens, few, plural } from './parts';
import type { Pane } from './pane';

export const QUIET_LINK =
    'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-[13px] text-muted-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.04] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:ring-foreground/[0.12]';
const PLUS =
    'grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground opacity-0 transition-[opacity,background-color] hover:bg-foreground/[0.07] hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100 disabled:pointer-events-none disabled:group-hover:opacity-40 [@media(hover:none)]:opacity-100';
const CARD =
    'group flex min-w-0 cursor-pointer flex-col rounded-[20px] border border-border bg-card text-left transition-colors hover:bg-foreground/[0.025] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-foreground/[0.08] dark:bg-foreground/[0.02] dark:hover:bg-foreground/[0.045]';

export function Overview(pane: Pane) {
    const { share, onAt, ask } = pane;
    const nav = useWorkNav();
    const faces = useAgentFaces();
    const enabled = useAgentsOnMachines();
    const working = share.agents.filter((a) => a.status === 'working');
    const needs = share.agents.filter((a) => a.status === 'needs');
    const quiet = share.agents.length - working.length - needs.length;
    const machines = share.of('machines');
    const upNow = share.up.sandboxes + share.up.keptOn + share.up.own;
    const plus = (k: SpaceKind) =>
        kindOf(k).make ? (
            <DisabledTip label={k === 'machines' && enabled === false ? AGENTS_NOT_ENABLED : kindOf(k).make} disabled={k === 'machines' && enabled === false}>
                <button
                    type="button"
                    aria-label={kindOf(k).make}
                    disabled={k === 'machines' && enabled === false}
                    onClick={(e) => {
                        e.stopPropagation();
                        ask({ kind: 'create', of: k });
                    }}
                    className={PLUS}
                >
                    <Plus className="h-4 w-4" strokeWidth={2} />
                </button>
            </DisabledTip>
        ) : null;
    const tile = (k: SpaceKind, detail: string, attention = false) => {
        if (!share.kinds.includes(k)) return null;
        const def = kindOf(k);
        const Icon = def.icon;
        const n = share.of(k).length;
        return (
            <Tile
                key={k}
                mark={
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-foreground/[0.05]">
                        <Icon className="h-[18px] w-[18px] text-foreground/75" strokeWidth={1.75} />
                    </span>
                }
                title={def.label}
                detail={!n ? 'None here' : attention ? <span className="text-red-600 dark:text-red-400">{detail}</span> : detail}
                label={`${def.label}: ${n}`}
                onOpen={() => onAt({ kind: k })}
                testId={`space-kind-${k}`}
                className="rounded-[20px]"
                trailing={
                    <span className="flex shrink-0 items-center gap-1 pl-1">
                        {plus(k)}
                        <span className={cn('w-5 text-right text-[15px] tabular-nums', n ? 'text-foreground/85' : 'text-muted-foreground/60')}>{n}</span>
                    </span>
                }
            />
        );
    };
    const names = (k: SpaceKind, max = 2) => few(share.of(k).map(titleFor), max);
    const broken = share.of('connections').find((t) => pane.connections.get(t.ref)?.status === 'disconnected');
    const failing = share.of('automations').find((t) => t.automation?.lastRun?.status === 'failed');
    const skillUsers = [...new Set(share.of('skills').flatMap((t) => t.usedBy))];
    const memories = share.of('memories');
    const ownMemories = memories.filter((t) => t.knowledge?.kind === 'memory' && t.knowledge.agentId).length;
    const secrets = share.of('secrets');
    const moved = secrets.filter((t) => t.movedFrom);
    const hosts = [...new Set(moved.map((t) => t.movedFrom!.host ?? 'a computer'))];
    const holders = [...new Set(secrets.flatMap((t) => t.usedBy.map((id) => share.agent(id)?.name ?? '')))].filter(Boolean);
    const answeredBy = [...new Set(share.of('email').flatMap((t) => t.usedBy.map((id) => share.agent(id)?.name).filter((n): n is string => !!n)))];
    return (
        <>
            <PageHead
                title="Resources"
                line="What people and agents here can use. Share one with the space and everyone in it gets it."
                actions={
                    pane.accountPage && (
                        <button type="button" onClick={() => pane.accountPage?.(null)} className={cn(QUIET_LINK, '@2xl:mt-1')}>
                            All of the account’s resources
                            <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={1.9} />
                        </button>
                    )
                }
            />

            <div className="mt-8 grid gap-2.5 @2xl:grid-cols-2">
                <Glance
                    label="Agents"
                    figure={share.agents.length}
                    unit={share.agents.length === 1 ? 'agent' : 'agents'}
                    legend={(
                        [
                            [working.length, 'working'],
                            [needs.length, needs.length === 1 ? 'needs you' : 'need you'],
                            [quiet, 'quiet'],
                        ] as [number, string][]
                    ).filter(([n]) => n > 0)}
                    onOpen={() => onAt({ kind: 'agents' })}
                    plus={plus('agents')}
                    empty="No agent is working or waiting on you."
                >
                    {[...needs, ...working].slice(0, 4).map((a) => (
                        <GlanceLine
                            key={a.id}
                            onOpen={() => nav.openProfile(a.id)}
                            lead={<AgentRing member={faces.get(a.id) ?? { id: a.id, kind: 'agent', name: a.name }} status={a.status} size={20} />}
                            name={a.name}
                            line={a.line}
                        />
                    ))}
                </Glance>
                <Glance
                    label="Machines"
                    figure={upNow}
                    unit="up now"
                    legend={[
                        [share.up.sandboxes, `of ${plural(machines.filter((t) => t.machine?.kind === 'sandbox').length, ['sandbox', 'sandboxes'])}`],
                        [share.up.keptOn, 'kept on'],
                        ...((share.up.own ? [[share.up.own, 'of yours']] : []) as [number, string][]),
                    ]}
                    onOpen={() => onAt({ kind: 'machines' })}
                    plus={plus('machines')}
                    empty="Nothing is running. Sandboxes start when an agent needs one."
                >
                    {machines
                        .filter((t) => t.machine?.state === 'running' || t.place?.status === 'running')
                        .slice(0, 4)
                        .map((t) => (
                            <GlanceLine
                                key={t.key}
                                onOpen={() => pane.open(t)}
                                lead={<span className="h-2 w-2 rounded-full bg-emerald-500" />}
                                name={t.name}
                                line={t.place ? `${placeState(t.place, pane.now)}${isOwn(t.place) && t.place.status === 'running' && !t.usedBy.length ? ' · no agent runs here now' : ''}` : (t.machine?.state ?? '')}
                            />
                        ))}
                </Glance>
            </div>

            <div className="mt-9 flex flex-col gap-9">
                <Group title={GROUPS.know}>
                    <div className="grid gap-2.5 @lg:grid-cols-2">
                        {tile(
                            'skills',
                            skillUsers.length > 2 && skillUsers.length === share.agents.length
                                ? `Used by all ${skillUsers.length} agents`
                                : skillUsers.length
                                  ? `Used by ${few(skillUsers.map((id) => share.agent(id)?.name ?? '').filter(Boolean))}`
                                  : 'No agent here uses one'
                        )}
                        {tile('memories', `${memories.length - ownMemories} shared, ${ownMemories} ${ownMemories === 1 ? 'agent’s' : 'agents’'} own`)}
                    </div>
                </Group>
                <Group title={GROUPS.reach}>
                    <div className="grid gap-2.5 @lg:grid-cols-2 @4xl:grid-cols-3">
                        {tile('automations', failing ? `${failing.name} failed` : names('automations'), !!failing)}
                        {tile('connections', broken ? `${broken.name} isn’t working` : names('connections'), !!broken)}
                        {tile('secrets', moved.length ? `${moved.length} moved from ${few(hosts)}` : `Held by ${few(holders) || 'no agent'}`)}
                        {tile('channels', names('channels', 1))}
                        {tile('code', few(share.of('code').map((t) => t.name.split('/').pop()!)))}
                        {tile('websites', names('websites'))}
                        {tile('databases', names('databases'))}
                        {tile('files', names('files', 1))}
                        {tile('numbers', names('numbers', 1))}
                        {tile('email', `Answered by ${few(answeredBy) || 'no agent'}`)}
                    </div>
                </Group>
            </div>
        </>
    );
}

/** One of the two big cards: how many, how they split, and the ones at work now. */
function Glance({ label, figure, unit, legend, onOpen, plus, empty, children }: { label: string; figure: number; unit: string; legend: [number, string][]; onOpen: () => void; plus: ReactNode; empty: string; children: ReactNode[] }) {
    return (
        <div role="button" tabIndex={0} aria-label={`${label}: ${figure} ${unit}`} onClick={onOpen} onKeyDown={enterOpens(onOpen)} className={cn(CARD, 'px-5 pb-4 pt-3.5')} data-testid={`glance-${label.toLowerCase()}`}>
            <p className="flex items-center gap-1 text-[13px] font-medium text-muted-foreground">
                {label}
                <span className="ml-auto flex items-center gap-1">
                    {plus}
                    <ChevronRight className="h-4 w-4 opacity-60 transition-transform duration-200 group-hover:translate-x-0.5" />
                </span>
            </p>
            <p className="mt-1 flex items-baseline gap-2">
                <span className={cn(DISPLAY, 'text-[46px] leading-none tabular-nums text-foreground')}>{figure}</span>
                <span className="text-[15px] text-muted-foreground">{unit}</span>
            </p>
            <p className="mt-2.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[13px] text-muted-foreground">
                {legend.map(([n, words]) => (
                    <span key={words}>
                        <span className={cn('tabular-nums', n ? 'font-medium text-foreground' : '')}>{n}</span> {words}
                    </span>
                ))}
            </p>
            <div className="-mx-2 mt-3 border-t border-border pt-2 dark:border-foreground/[0.07]">
                {children.length ? <ul className="flex flex-col">{children}</ul> : <p className="px-2 py-1.5 text-[13px] text-muted-foreground">{empty}</p>}
            </div>
        </div>
    );
}

function GlanceLine({ lead, name, line, onOpen }: { lead: ReactNode; name: string; line: string; onOpen: () => void }) {
    return (
        <li>
            <button
                type="button"
                onClick={(e) => {
                    e.stopPropagation();
                    onOpen();
                }}
                className="flex h-8 w-full min-w-0 items-center gap-2.5 rounded-full px-2 text-left text-[13.5px] transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
                <span className="grid w-5 shrink-0 place-items-center">{lead}</span>
                <span className="shrink-0 font-medium text-foreground">{name}</span>
                <span className="min-w-0 truncate text-muted-foreground">{line}</span>
            </button>
        </li>
    );
}

/** A group on the overview or a list, set apart by space rather than rules. */
export function Group({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
    return (
        <section>
            <h2 className="mb-2.5 flex items-baseline gap-2 text-[13px] font-medium text-muted-foreground">
                {title}
                {meta != null && <span className="font-normal tabular-nums text-muted-foreground/80">{meta}</span>}
            </h2>
            {children}
        </section>
    );
}

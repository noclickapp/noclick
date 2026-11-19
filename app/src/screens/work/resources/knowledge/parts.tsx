// The small parts a skill's or memory's page, its rows and its pickers share: its mark, the faces of the agents that
// use it, who wrote something, a link's access or version picked in place, and the list of agents using it.
import { useContext, type ReactNode } from 'react';
import { BookOpen, Brain, Check, ChevronDown, KeyRound, UserRound, X } from 'lucide-react';
import { useWorkClient } from '../../client';
import { WorkNavContext } from '../../nav';
import { HarnessMark, harnessLabel } from '../../agents/harness';
import { useAgentFaces } from '../../agents/reads';
import type { Knowledge, MemoryItem, Skill, Writer } from '@/screens/resources/knowledge';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { MemberAvatar, type AvatarSize } from '@/screens/channels/avatars';
import type { ChannelMember } from '@/screens/channels/types';
import { FIELD } from '@/ui/fields';
import { MENU_SURFACE } from '@/ui/menus';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { detachWithUndo, relink, titleOf, useKnowledge, writeRefusal, type Use } from './store';

export const ICON_BUTTON =
    'grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
export const SMALL_PRIMARY = BUTTON_PRIMARY.replace('h-9', 'h-8').replace('px-4', 'px-3.5');
export const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace('px-4', 'px-3');
export const XS = 'inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
/** One-line fields are pills here; a multi-line one keeps the field's rounded corners. */
export { PILL_FIELD } from '@/ui/fields';
export const AREA = `${FIELD.replace('h-10 ', '')} py-2.5 leading-relaxed`;
export const MENU_ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';
export const MENU_RULE = 'mx-1 bg-border dark:bg-foreground/[0.08]';

export const list = (names: string[]) => new Intl.ListFormat('en', { type: 'conjunction' }).format(names);

export function ItemMark({ kind, className, iconClassName }: { kind: Knowledge['kind']; className?: string; iconClassName?: string }) {
    const Icon = kind === 'skill' ? BookOpen : Brain;
    return (
        <span className={cn('grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/75', className)}>
            <Icon className={cn('h-[15px] w-[15px]', iconClassName)} strokeWidth={1.75} />
        </span>
    );
}

export function Chip({ children }: { children: ReactNode }) {
    return <span className="inline-flex h-6 items-center gap-1 rounded-full bg-foreground/[0.06] px-2.5 text-[12px] text-muted-foreground">{children}</span>;
}

/** An agent's face: the letters and colour it wears everywhere in Work. */
export function useFaceOf(): (agent: { id: string; name: string }) => ChannelMember {
    const faces = useAgentFaces();
    return (agent) => faces.get(agent.id) ?? { id: agent.id, kind: 'agent', name: agent.name || '?', agentId: agent.id };
}

export function AgentFace({ agent, size = 20, className }: { agent: { id: string; name: string }; size?: AvatarSize; className?: string }) {
    const faceOf = useFaceOf();
    return <MemberAvatar member={faceOf(agent)} size={size} className={className} />;
}

export function Faces({ agents, size = 20 }: { agents: { id: string; name: string }[]; size?: AvatarSize }) {
    const faceOf = useFaceOf();
    return (
        <span className="flex shrink-0 -space-x-1.5">
            {agents.slice(0, 3).map((a) => (
                <MemberAvatar key={a.id} member={faceOf(a)} size={size} className="ring-2 ring-card dark:ring-background" />
            ))}
        </span>
    );
}

/** Who wrote something: the agent as it worked, a person in the app, or a key. */
export function WriterFace({ who, size = 16 }: { who: Writer | null; size?: AvatarSize }) {
    if (who?.type === 'agent' && who.agentId) return <AgentFace agent={{ id: who.agentId, name: who.agentName ?? '' }} size={size} />;
    if (who?.type === 'api') {
        return (
            <span className={cn('grid shrink-0 place-items-center rounded-full bg-foreground/[0.08] text-foreground/70', size === 16 ? 'h-4 w-4' : size === 20 ? 'h-5 w-5' : 'h-6 w-6')}>
                <KeyRound className="h-[60%] w-[60%]" strokeWidth={2} />
            </span>
        );
    }
    return (
        <span className={cn('grid shrink-0 place-items-center rounded-full bg-foreground/[0.1] text-foreground/70', size === 16 ? 'h-4 w-4' : size === 20 ? 'h-5 w-5' : 'h-6 w-6')}>
            <UserRound className="h-[62%] w-[62%]" strokeWidth={2} />
        </span>
    );
}

export function writerName(who: Writer | null): string {
    if (who?.type === 'agent') return who.agentName ?? 'An agent';
    if (who?.type === 'api') return 'Your code';
    return 'A person';
}

/** Where someone opening an agent goes: its profile in Work, where Work is open (none in the account's Resources). */
export function useOpenAgent(): ((agentId: string) => void) | undefined {
    const nav = useContext(WorkNavContext);
    return nav ? (agentId) => nav.openProfile(agentId) : undefined;
}

const PICK_TRIGGER =
    'relative z-[1] -mx-1.5 inline-flex h-6 items-center gap-0.5 rounded-full px-1.5 transition-colors hover:bg-foreground/[0.06] hover:text-foreground data-[state=open]:bg-foreground/[0.06]';

function PickItem({ on, title, note, onSelect }: { on: boolean; title: string; note: string; onSelect: () => void }) {
    return (
        <DropdownMenuItem onSelect={onSelect} className="items-start gap-2.5 rounded-lg px-2.5 py-2">
            <Check className={cn('mt-0.5 h-4 w-4 shrink-0', on ? 'opacity-100' : 'opacity-0')} strokeWidth={2} />
            <span className="min-w-0">
                <span className="block text-[14px]">{title}</span>
                <span className="block truncate text-xs text-muted-foreground">{note}</span>
            </span>
        </DropdownMenuItem>
    );
}

/** A memory link's access, picked in place: whether the agent saves to it or only reads it. */
export function AccessPill({ use, memory }: { use: Use; memory: MemoryItem }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const writes = !!use.link?.writes;
    const refusal = writeRefusal(use.agent, memory, memory.agentId ? k.agent(memory.agentId) : undefined);
    const label = writes ? 'Can edit' : 'Reads only';
    if (refusal)
        return (
            <ShortcutTooltip label={refusal}>
                <span>{label}</span>
            </ShortcutTooltip>
        );
    return (
        <DropdownMenu>
            <DropdownMenuTrigger className={PICK_TRIGGER}>
                {label}
                <ChevronDown className="h-3 w-3" strokeWidth={2} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" sideOffset={4} className={cn('w-[250px] rounded-xl p-1', MENU_SURFACE)}>
                <PickItem on={writes} title="Reads and writes" note={`${use.agent.name} saves what it learns here`} onSelect={() => void relink(client, use.agent, memory, { writes: true })} />
                <PickItem on={!writes} title="Reads only" note="It reads; only you and others change it" onSelect={() => void relink(client, use.agent, memory, { writes: false })} />
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

/** A skill link's version: the latest, or held at one of its versions. */
export function PinPill({ use, skill, versions }: { use: Use; skill: Skill; versions: { version: number; note: string }[] }) {
    const client = useWorkClient();
    const pin = use.link?.pin ?? null;
    return (
        <DropdownMenu>
            <DropdownMenuTrigger className={PICK_TRIGGER}>
                {pin ? `Pinned to v${pin}` : 'Latest'}
                <ChevronDown className="h-3 w-3" strokeWidth={2} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" sideOffset={4} className={cn('w-[250px] rounded-xl p-1', MENU_SURFACE)}>
                <PickItem on={!pin} title={`Follow the latest (v${skill.version})`} note="Gets each change from its next conversation" onSelect={() => void relink(client, use.agent, skill, { pin: null })} />
                <DropdownMenuSeparator className={MENU_RULE} />
                {versions.map((v) => (
                    <PickItem key={v.version} on={pin === v.version} title={`Hold at v${v.version}`} note={v.note} onSelect={() => void relink(client, use.agent, skill, { pin: v.version })} />
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

/** A section of an item's page: its title, a figure, and an action at its right. */
export function PageSection({ title, meta, children, action }: { title: string; meta?: ReactNode; children: ReactNode; action?: ReactNode }) {
    return (
        <section className="mt-8">
            <div className="flex items-center gap-2">
                <h3 className="text-[13px] font-medium">{title}</h3>
                {meta != null && <span className="text-[13px] tabular-nums text-muted-foreground">{meta}</span>}
                <span className="flex-1" />
                {action}
            </div>
            <div className="mt-2">{children}</div>
        </section>
    );
}

/** The agents using it, each with what it may do (a memory's access, a skill's version), to detach in place. */
export function UsedByList({ item, versions = [] }: { item: Knowledge; versions?: { version: number; note: string }[] }) {
    const client = useWorkClient();
    const k = useKnowledge();
    const open = useOpenAgent();
    const users = k.usersOf(item);
    if (!users.length) return <p className="text-sm text-muted-foreground">No agent uses it yet. Attach it to one, or leave it here for later.</p>;
    const owner = item.kind === 'memory' && item.agentId ? k.agent(item.agentId) : undefined;
    return (
        <ul className="-mx-2.5">
            {users.map((use) => (
                <li key={use.agent.id} className="group flex items-center gap-3 rounded-xl px-2.5 py-2 hover:bg-foreground/[0.04]">
                    <AgentFace agent={use.agent} size={28} />
                    <div className="min-w-0 flex-1">
                        {open ? (
                            <button type="button" onClick={() => open(use.agent.id)} className="text-sm font-medium hover:underline">
                                {use.agent.name}
                            </button>
                        ) : (
                            <p className="text-sm font-medium">{use.agent.name}</p>
                        )}
                        <p className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                            <HarnessMark harness={use.agent.harness} className="h-3 w-3" />
                            {harnessLabel(use.agent.harness)}
                            {use.agent.model ? ` · ${use.agent.model}` : ''}
                        </p>
                    </div>
                    <span className="text-xs text-muted-foreground">
                        {!use.link ? 'Its own: writes' : item.kind === 'memory' ? <AccessPill use={use} memory={item} /> : <PinPill use={use} skill={item} versions={versions} />}
                    </span>
                    {use.link ? (
                        <button
                            type="button"
                            aria-label={`Detach from ${use.agent.name}`}
                            onClick={() => void detachWithUndo(client, use.agent, item, titleOf(item, owner))}
                            className={cn(ICON_BUTTON, 'h-7 w-7 opacity-0 focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100')}
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                    ) : (
                        <span className="w-7" />
                    )}
                </li>
            ))}
        </ul>
    );
}

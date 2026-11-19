// The channel header's faces and count, as Slack's: they open who's in the channel (people, then agents, each with
// what it's doing), found by name; a person opens your DM with them and an agent its profile. From there you add one
// of your agents, or take a member out. A channel made mention-only before says so here, with the way to every message.
import { useRef, useState } from 'react';
import { ChevronLeft, Plus, UserPlus, X } from 'lucide-react';
import type { AccountMenuUser } from '@/ui/accountParts';
import { Facepile, MemberAvatar, presenceFace } from '@/screens/channels/avatars';
import { AgentChoiceRow } from '@/screens/channels/AgentChoiceRow';
import { agentGroups, agentKey, YOU } from '@/screens/channels/model';
import type { AgentChoice, Channel, ChannelMember } from '@/screens/channels/types';
import { MENU_SURFACE } from '@/ui/menus';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { MORE_AGENTS } from '@/screens/channels/slots';
import { useSlot } from '@/slots';
import { usePickerAgents } from './pickerAgents';
import { SearchField } from './tabs';

const CIRCLE = 'grid h-8 w-8 shrink-0 place-items-center rounded-full max-md:h-10 max-md:w-10 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70';
const ROW = 'flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors';

/** What a member is, under its name: what an agent's doing or its job, a person's kind. */
function detailOf(m: ChannelMember): string {
    if (m.kind === 'you') return 'You';
    if (m.kind === 'outside') return 'Outside agent';
    if (m.kind !== 'agent') return 'Person';
    if (m.busy) return 'Working…';
    return m.role ?? (m.workflowName ? `Agent in ${m.workflowName}` : 'Agent');
}

export function ChannelMembers({
    channel,
    members,
    agents,
    user,
    onMember,
    onAdd,
    onRemove,
    onAnswerEveryMessage,
}: {
    channel: Channel;
    /** Everyone in it but you. */
    members: ChannelMember[];
    /** Your agents, to add. */
    agents: AgentChoice[];
    user: AccountMenuUser;
    onMember: (member: ChannelMember) => void;
    onAdd: (agent: AgentChoice) => void;
    onRemove: (member: ChannelMember) => void;
    onAnswerEveryMessage: () => void;
}) {
    const [open, setOpen] = useState(false);
    const [adding, setAdding] = useState(false);
    const [query, setQuery] = useState('');
    const search = useRef<HTMLInputElement>(null);
    const total = members.length + 1;
    const q = query.trim().toLowerCase();
    const hit = (m: { name: string }, more = '') => !q || `${m.name} ${more}`.toLowerCase().includes(q);
    const people = [YOU, ...members.filter((m) => m.kind === 'human')].filter((m) => hit(m.id === YOU.id ? { name: user.display_name ?? 'You' } : m, m.id === YOU.id ? 'you' : ''));
    const inRoom = members.filter((m) => m.kind === 'agent' || m.kind === 'outside');
    const shownAgents = inRoom.filter((m) => hit(m, m.role ?? ''));
    const choices = usePickerAgents(agents, open && adding, channel.workspaceId ?? null);
    const moreLabel = useSlot(MORE_AGENTS)?.label ?? null;
    const addable = agentGroups(choices.filter((a) => !members.some((m) => agentKey(m) === a.id) && hit(a, `${a.role ?? ''} ${a.modelLine ?? ''}`)), moreLabel);
    const closed = channel.status === 'closed';
    const pick = (m: ChannelMember) => {
        setOpen(false);
        onMember(m);
    };
    const faces = inRoom.length ? inRoom : members.length ? members : [YOU];

    return (
        <Popover
            open={open}
            onOpenChange={(o) => {
                setOpen(o);
                if (!o) {
                    setQuery('');
                    setAdding(false);
                }
            }}
        >
            <ShortcutTooltip label="Members">
                <PopoverTrigger
                    aria-label={`${total} members`}
                    data-testid="channel-members"
                    className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full py-1 pl-1.5 pr-2.5 max-md:h-10 transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 aria-expanded:bg-foreground/[0.07]"
                >
                    <Facepile members={faces.slice(0, 3)} user={user} size={20} />
                    <span className="text-xs font-medium tabular-nums text-muted-foreground">{total}</span>
                </PopoverTrigger>
            </ShortcutTooltip>
            <PopoverContent
                align="end"
                sideOffset={8}
                collisionPadding={12}
                onOpenAutoFocus={(e) => {
                    e.preventDefault();
                    search.current?.focus();
                }}
                className={cn('w-[340px] max-w-[calc(100vw-24px)] rounded-2xl p-0', MENU_SURFACE)}
            >
                <div className="flex items-center gap-2 pb-2 pl-4 pr-2 pt-2.5">
                    {adding && (
                        <button type="button" aria-label="Back to the members" onClick={() => setAdding(false)} className={cn(CIRCLE, '-ml-2 h-7 w-7')}>
                            <ChevronLeft className="h-4 w-4" />
                        </button>
                    )}
                    <p className="text-[15px] font-semibold">{adding ? 'Add an agent' : `${total} members`}</p>
                    <p className="min-w-0 truncate text-[12.5px] text-muted-foreground">#{channel.name}</p>
                    <button type="button" aria-label="Close" onClick={() => setOpen(false)} className={cn(CIRCLE, 'ml-auto')}>
                        <X className="h-4 w-4" />
                    </button>
                </div>
                <div className="px-3 pb-2">
                    <SearchField value={query} onChange={setQuery} placeholder={adding ? 'Find one of your agents' : 'Find people and agents'} inputRef={search} />
                </div>
                <div className="max-h-[440px] overflow-y-auto px-1.5 pb-1.5 scrollbar-subtle">
                    {adding ? (
                        addable.length ? (
                            addable.map((group) => (
                                <section key={group.label} aria-label={group.label || undefined}>
                                    {group.label && <p className="px-2.5 pb-1 pt-2.5 text-xs font-medium text-muted-foreground">{group.label}</p>}
                                    {group.agents.map((a) => (
                                        <button
                                            key={a.id}
                                            type="button"
                                            onClick={() => {
                                                onAdd(a);
                                                setAdding(false);
                                                setQuery('');
                                            }}
                                            className={cn(ROW, 'hover:bg-foreground/[0.05]')}
                                        >
                                            <AgentChoiceRow agent={a} user={user} />
                                            <Plus className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                        </button>
                                    ))}
                                </section>
                            ))
                        ) : (
                            <p className="px-2.5 py-6 text-center text-[13px] text-muted-foreground">{agents.length ? 'Every one of your agents is here.' : 'You have no agents yet. Make one in Agents.'}</p>
                        )
                    ) : (
                        <>
                            {!q && !closed && channel.mode === 'mentions' && (
                                <p className="px-2.5 pb-1.5 pt-1 text-[12.5px] leading-snug text-muted-foreground" data-testid="mentions-only">
                                    Agents here answer only when @-mentioned.{' '}
                                    <button
                                        type="button"
                                        onClick={onAnswerEveryMessage}
                                        className="font-medium text-foreground/80 underline decoration-foreground/25 underline-offset-[3px] hover:text-foreground"
                                    >
                                        Answer every message
                                    </button>
                                </p>
                            )}
                            {!q && !closed && (
                                <button type="button" onClick={() => setAdding(true)} className={cn(ROW, 'hover:bg-foreground/[0.05]')}>
                                    <span className="grid h-7 w-7 place-items-center rounded-full bg-foreground/[0.06]">
                                        <UserPlus className="h-3.5 w-3.5 text-foreground/80" strokeWidth={2} />
                                    </span>
                                    <span className="text-[14px]">Add an agent</span>
                                </button>
                            )}
                            {people.length > 0 && <p className="px-2.5 pb-1 pt-2.5 text-xs font-medium text-muted-foreground">People · {people.length}</p>}
                            {people.map((m) => {
                                const you = m.id === YOU.id;
                                const inner = (
                                    <>
                                        <MemberAvatar member={m} user={user} size={28} />
                                        <span className="min-w-0 flex-1">
                                            <span className="block truncate text-[14px] font-medium">
                                                {you ? (user.display_name ?? 'You') : m.name}
                                                {you && <span className="font-normal text-muted-foreground"> (you)</span>}
                                            </span>
                                            <span className="block truncate text-xs text-muted-foreground">{detailOf(m)}</span>
                                        </span>
                                    </>
                                );
                                return you ? (
                                    <div key={m.id} className={ROW}>
                                        {inner}
                                    </div>
                                ) : (
                                    <MemberRow key={m.id} member={m} closed={closed} onPick={() => pick(m)} onRemove={() => onRemove(m)}>
                                        {inner}
                                    </MemberRow>
                                );
                            })}
                            {shownAgents.length > 0 && (
                                <p className="px-2.5 pb-1 pt-2.5 text-xs font-medium text-muted-foreground">Agents · {shownAgents.length}</p>
                            )}
                            {shownAgents.map((m) => (
                                <MemberRow key={m.id} member={m} closed={closed} onPick={() => pick(m)} onRemove={() => onRemove(m)}>
                                    <MemberAvatar member={m} user={user} size={28} state={presenceFace(m)} />
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate text-[14px] font-medium">{m.name}</span>
                                        <span className="block truncate text-xs text-muted-foreground">{detailOf(m)}</span>
                                    </span>
                                </MemberRow>
                            ))}
                            {q && !people.length && !shownAgents.length && <p className="px-2.5 py-6 text-center text-[13px] text-muted-foreground">No one here matches “{query.trim()}”.</p>}
                        </>
                    )}
                </div>
            </PopoverContent>
        </Popover>
    );
}

function MemberRow({ member, closed, onPick, onRemove, children }: { member: ChannelMember; closed: boolean; onPick: () => void; onRemove: () => void; children: React.ReactNode }) {
    return (
        <div className="group flex items-center rounded-xl transition-colors hover:bg-foreground/[0.05]">
            <button type="button" onClick={onPick} className={cn(ROW, 'min-w-0 flex-1')}>
                {children}
            </button>
            {!closed && (
                <button
                    type="button"
                    onClick={onRemove}
                    aria-label={`Remove ${member.name}`}
                    className="mr-1.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground opacity-0 transition-opacity hover:bg-foreground/[0.06] hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
                >
                    <X className="h-3.5 w-3.5" strokeWidth={2} />
                </button>
            )}
        </div>
    );
}

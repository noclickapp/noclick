// Who's in a space and what they can reach, beside what's open: its people (you first, then each with their role,
// changed in place by those who manage it, then who's been invited), its agents (added from yours, or taken out),
// and what members can reach.
import type { ReactNode } from 'react';
import { Check, ChevronDown, Mail, Plus, UserPlus } from 'lucide-react';
import { toast } from 'sonner';
import type { AccountMenuUser } from '@/ui/accountParts';
import { HAIRLINE } from '@/ui/primitives';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { MemberAvatar } from '@/screens/channels/avatars';
import { YOU } from '@/screens/channels/model';
import type { AgentChoice } from '@/screens/channels/types';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';
import type { WorkspaceMember, WorkspaceRole } from 'noclick';
import { keptByNoClick, useAgentFaces } from '../agents/reads';
import type { WorkPanel } from '../place';
import type { WorkSpace } from '../spaces';
import { CloseButton, PanelFrame } from '../ui';
import { AccessTable } from './AccessTable';
import type { SpacePeople } from './members';

type MembersTab = Exclude<WorkPanel, 'profile'>;

const SMALL_PRIMARY = BUTTON_PRIMARY.replace('h-9', 'h-8');
const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace('px-4', 'px-3');
const SMALL_GHOST = BUTTON_GHOST.replace('h-9', 'h-8');

export const ROLES: { role: WorkspaceRole; label: string; note: string }[] = [
    { role: 'admin', label: 'Admin', note: 'Invites people and changes the space' },
    { role: 'member', label: 'Member', note: 'Every agent, channel and connected resource' },
    { role: 'guest', label: 'Guest', note: 'Only the channels you add them to' },
];
export const roleLabel = (role: string | null) => (role === 'owner' ? 'Owner' : (ROLES.find((r) => r.role === role)?.label ?? 'Member'));

/** "Online", "Last active 2h ago", from when a person was last seen. */
export function presenceOf(seen: Date | null, now = Date.now()): string | null {
    if (!seen) return null;
    const minutes = Math.round((now - seen.getTime()) / 60_000);
    if (minutes < 5) return 'Online';
    if (minutes < 60) return `Last active ${minutes}m ago`;
    if (minutes < 60 * 24) return `Last active ${Math.round(minutes / 60)}h ago`;
    return `Last active ${Math.round(minutes / 60 / 24)}d ago`;
}

export function MembersPanel({
    space,
    people,
    tab,
    user,
    agents,
    phone,
    onTab,
    onClose,
    onInvite,
    onAgent,
    onPerson,
}: {
    space: WorkSpace;
    people: SpacePeople;
    tab: MembersTab;
    user: AccountMenuUser;
    /** Your agents, to add to the space. */
    agents: AgentChoice[];
    phone: boolean;
    onTab: (tab: MembersTab) => void;
    onClose: () => void;
    onInvite: () => void;
    onAgent: (agentId: string) => void;
    onPerson: (member: WorkspaceMember) => void;
}) {
    const faces = useAgentFaces();
    const others = people.people.filter((p) => p.userId !== space.userId);
    // A personal space's agents are the ones in its channels, never added to it.
    const personal = !space.workspaceId || space.personal;
    const tabs: [MembersTab, string][] = [
        ['people', `People ${others.length + 1}`],
        ...(personal ? [] : [['agents', `Agents ${people.agents.length}`] as [MembersTab, string]]),
        ['access', 'Access'],
    ];
    const act = (work: Promise<void>, done?: string) =>
        work.then(
            () => done && toast(done),
            (e: Error) => toast.error(e.message)
        );
    return (
        <PanelFrame phone={phone}>
            {/* On a phone the bar above names it and carries the way back. */}
            {!phone && (
                <div className="flex items-center gap-2 px-5 pb-3 pt-4">
                    <p className="text-[16px] font-semibold">Members</p>
                    <p className="truncate text-[13px] text-muted-foreground">{space.workspaceId ? space.name : 'Your personal space'}</p>
                    <CloseButton onClose={onClose} />
                </div>
            )}
            <div role="tablist" aria-label="Members" className={cn('flex gap-5 border-b px-5', HAIRLINE, phone && 'pt-1')} data-testid="members-panel">
                {tabs.map(([id, label]) => (
                    <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={tab === id}
                        onClick={() => onTab(id)}
                        className={cn('-mb-px border-b-2 pb-2.5 text-[13.5px] transition-colors max-md:pt-2 max-md:text-[15px]', tab === id ? 'border-foreground font-medium text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground')}
                    >
                        {label}
                    </button>
                ))}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-subtle">
                {people.error && (
                    <p role="alert" className="px-2 pb-3 text-[13px] text-muted-foreground">
                        {people.error}
                    </p>
                )}
                {tab === 'people' && (
                    <>
                        <div className="flex items-center gap-3 px-2 pb-3">
                            {people.manages && (
                                <button type="button" onClick={onInvite} className={SMALL_PRIMARY}>
                                    <UserPlus className="h-4 w-4" strokeWidth={1.9} />
                                    Invite people
                                </button>
                            )}
                            {people.peopleLimit !== null && (
                                <span className="ml-auto text-[12.5px] tabular-nums text-muted-foreground">
                                    {people.peopleCount} of {people.peopleLimit} people
                                </span>
                            )}
                        </div>
                        <MemberLine face={<MemberAvatar member={YOU} user={user} size={32} />} name={`${user.display_name || user.email} (you)`} detail={user.email} right={<span className="pr-2 text-[13px] text-muted-foreground">{roleLabel(people.role)}</span>} />
                        {space.accountName && (
                            <MemberLine
                                face={<MemberAvatar member={{ id: 'owner', kind: 'human', name: space.accountName }} size={32} />}
                                name={space.accountName}
                                detail="Owns this space"
                                right={<span className="pr-2 text-[13px] text-muted-foreground">Owner</span>}
                            />
                        )}
                        {others.map((p) => (
                            <MemberLine
                                key={p.id}
                                face={<MemberAvatar member={{ id: p.id, kind: 'human', name: p.name ?? p.email ?? 'Someone' }} size={32} />}
                                name={p.name ?? p.email ?? 'Someone'}
                                detail={[presenceOf(p.lastSeenAt), p.email].filter(Boolean).join(' · ')}
                                onClick={() => onPerson(p)}
                                right={
                                    people.manages ? (
                                        <RoleMenu role={p.role ?? 'member'} name={p.name ?? 'them'} onRole={(r) => act(people.setRole(p, r))} onRemove={() => act(people.remove(p), `${p.name ?? 'They'} left ${space.name}`)} />
                                    ) : (
                                        <span className="pr-2 text-[13px] text-muted-foreground">{roleLabel(p.role)}</span>
                                    )
                                }
                            />
                        ))}
                        {people.manages && people.invites.some((i) => i.type === 'email') && (
                            <>
                                <p className="px-2 pb-1 pt-4 text-[12.5px] font-medium text-muted-foreground">Invited</p>
                                {people.invites
                                    .filter((i) => i.type === 'email')
                                    .map((i) => (
                                        <MemberLine
                                            key={i.id}
                                            face={
                                                <span className="grid h-8 w-8 place-items-center rounded-full bg-foreground/[0.06]">
                                                    <Mail className="h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                                                </span>
                                            }
                                            name={i.email ?? 'An email invite'}
                                            detail={`${roleLabel(i.role)}${i.expiresAt ? ` · until ${i.expiresAt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : ''}`}
                                            right={
                                                <span className="flex items-center">
                                                    <button type="button" onClick={() => act(people.resend(i), `Invite sent again to ${i.email}`)} className={SMALL_GHOST}>
                                                        Resend
                                                    </button>
                                                    <button type="button" onClick={() => act(people.revoke(i), 'Invite turned off')} className={SMALL_GHOST}>
                                                        Revoke
                                                    </button>
                                                </span>
                                            }
                                        />
                                    ))}
                            </>
                        )}
                    </>
                )}
                {tab === 'agents' && (
                    <>
                        {people.manages && <AddAgent agents={agents.filter((a) => !keptByNoClick(a) && !people.agents.some((m) => m.agentId === a.id))} onAdd={(id, name) => act(people.addAgent(id), `${name} joined ${space.name}`)} />}
                        {people.agents.map((a) => {
                            const face = faces.get(a.agentId ?? '') ?? { id: a.id, kind: 'agent' as const, name: a.name ?? 'Agent' };
                            return (
                                <MemberLine
                                    key={a.id}
                                    face={<MemberAvatar member={face} size={32} />}
                                    name={a.name ?? 'Agent'}
                                    detail={face.role ?? 'Agent'}
                                    onClick={() => a.agentId && onAgent(a.agentId)}
                                    right={
                                        people.manages && (
                                            <button type="button" onClick={() => act(people.remove(a), `${a.name} left ${space.name}; it stays yours`)} className={SMALL_GHOST}>
                                                Remove
                                            </button>
                                        )
                                    }
                                />
                            );
                        })}
                        {!people.agents.length && !people.loading && <p className="px-2 pt-1 text-[13px] text-muted-foreground">No agents in this space yet.</p>}
                        <p className="px-2 pt-3 text-[12.5px] leading-snug text-muted-foreground">Everyone here can message these agents and add them to channels. What they set off is paid by the space’s owner.</p>
                    </>
                )}
                {tab === 'access' && <AccessTable space={space} manages={people.manages} />}
            </div>
        </PanelFrame>
    );
}

function MemberLine({ face, name, detail, right, onClick }: { face: ReactNode; name: string; detail: string; right?: ReactNode; onClick?: () => void }) {
    const inner = (
        <>
            {face}
            <span className="min-w-0 flex-1 text-left">
                <span className="block truncate text-[14px] font-medium">{name}</span>
                <span className="block truncate text-[12.5px] text-muted-foreground">{detail}</span>
            </span>
        </>
    );
    return (
        <div className="flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-foreground/[0.03]" data-testid="member-line">
            {onClick ? (
                <button type="button" onClick={onClick} className="flex min-w-0 flex-1 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    {inner}
                </button>
            ) : (
                <span className="flex min-w-0 flex-1 items-center gap-3">{inner}</span>
            )}
            {right}
        </div>
    );
}

/** A person's role, changed in place, or taking them out of the space. */
function RoleMenu({ role, name, onRole, onRemove }: { role: WorkspaceRole; name: string; onRole: (role: WorkspaceRole) => void; onRemove: () => void }) {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label={`${name}’s role`}
                className="inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground data-[state=open]:bg-foreground/[0.06]"
            >
                {roleLabel(role)}
                <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" sideOffset={6} className="w-[260px] rounded-xl p-1">
                {ROLES.map((r) => (
                    <DropdownMenuItem key={r.role} onSelect={() => r.role !== role && onRole(r.role)} className="items-start gap-2.5 rounded-lg px-2.5 py-2 text-[14px]">
                        <Check className={cn('mt-0.5 h-4 w-4 shrink-0', r.role === role ? 'opacity-100' : 'opacity-0')} strokeWidth={2} />
                        <span>
                            <span className="block">{r.label}</span>
                            <span className="block text-[12.5px] text-muted-foreground">{r.note}</span>
                        </span>
                    </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator className="mx-1 bg-border dark:bg-foreground/[0.08]" />
                <DropdownMenuItem onSelect={onRemove} className="rounded-lg px-2.5 py-2 text-[14px] text-red-600 dark:text-red-400">
                    Remove from space
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

/** Adding one of your agents to the space. */
function AddAgent({ agents, onAdd }: { agents: AgentChoice[]; onAdd: (id: string, name: string) => void }) {
    return (
        <div className="px-2 pb-3">
            <DropdownMenu>
                <DropdownMenuTrigger className={SMALL_SECONDARY}>
                    <Plus className="h-4 w-4" strokeWidth={2} />
                    Add an agent
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" sideOffset={6} className="max-h-[320px] w-[260px] overflow-y-auto rounded-xl p-1">
                    {agents.length ? (
                        agents.map((a) => (
                            <DropdownMenuItem key={a.id} onSelect={() => onAdd(a.id, a.name)} className="gap-2.5 rounded-lg px-2.5 py-2 text-[14px]">
                                {a.name}
                            </DropdownMenuItem>
                        ))
                    ) : (
                        <p className="px-2.5 py-2 text-[13px] text-muted-foreground">Every one of your agents is here.</p>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    );
}

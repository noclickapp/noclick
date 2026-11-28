// The space's name atop its list, Slack's way: the name itself opens the space's menu (inviting people, who's in it,
// what members can reach, its name and logo, saving one of yours as a template; archiving or deleting one of yours,
// leaving one you joined), with no icons beside it. A space is made from the rail's + alone (a phone, which has none,
// from the spaces its menu switches between). Your personal space is never archived, deleted or saved as a template.
import type { ReactNode } from 'react';
import { Archive, ArchiveRestore, ChevronDown, KeyRound, LayoutTemplate, LogOut, MessageCircleQuestion, Pencil, Plus, Trash2, UserPlus, UsersRound } from 'lucide-react';
import { WorkspaceTile } from '@/screens/channels/workspaces';
import { MENU_SURFACE } from '@/ui/menus';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';
import type { WorkPanel } from './place';
import { ASKED_TITLE } from './questions';
import type { SpaceAsk } from './spaceSettings';
import { isYourPersonal, type WorkSpace } from './spaces';

const ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px] max-md:py-2.5 max-md:text-[15px]';
const ICON = 'h-4 w-4 text-muted-foreground';
const SEPARATOR = 'mx-1 bg-border dark:bg-foreground/[0.08]';
const DANGER = cn(ITEM, 'text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400');

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function SpaceHeader({
    space,
    spaces,
    onSpace,
    people,
    agents,
    onInvite,
    onMembers,
    onEdit,
    onNewSpace,
    onAsk,
    onUnarchive,
    onSaveTemplate,
    asked = 0,
    end,
}: {
    space: WorkSpace;
    /** On a phone, which has no rail: the spaces to switch to. */
    spaces?: WorkSpace[];
    onSpace: (id: string) => void;
    /** How many people and agents are in it, when known. */
    people: number | null;
    agents: number | null;
    onInvite: () => void;
    onMembers: (tab: Exclude<WorkPanel, 'profile'>) => void;
    onEdit: () => void;
    /** A phone's way to make a space, among the spaces it switches between. */
    onNewSpace: () => void;
    /** Asks before archiving or deleting one of yours, or leaving one you joined. */
    onAsk: (ask: SpaceAsk) => void;
    onUnarchive: () => void;
    /** Saves one of your spaces as a template: its setup, into a repository of yours. */
    onSaveTemplate: () => void;
    /** How many questions your NoClick asked the space's: when any, they're a menu row of their own. */
    asked?: number;
    /** At the row's other end: the list's fold glyph, where the list folds. */
    end?: ReactNode;
}) {
    const yours = isYourPersonal(space);
    const name = (
        <>
            {spaces && <WorkspaceTile workspace={space} size={28} />}
            <span className="truncate">{space.name}</span>
        </>
    );
    const manages = space.role === 'owner' || space.role === 'admin';
    const counts = [people !== null && plural(people, 'person', 'people'), agents !== null && plural(agents, 'agent', 'agents')].filter(Boolean).join(' · ');
    return (
        <div data-space-head className="flex h-12 shrink-0 items-center pl-2 pr-2.5">
            <DropdownMenu>
                <DropdownMenuTrigger
                    data-testid="space-menu"
                    className="group/space flex min-w-0 items-center gap-1.5 rounded-full px-2 py-1 text-[15px] font-semibold max-md:py-1.5 transition-colors hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.06]"
                >
                    {name}
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/space:rotate-180" strokeWidth={2} />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" sideOffset={6} className={cn('w-[280px] rounded-2xl p-1.5', MENU_SURFACE)}>
                    <div className="flex items-center gap-3 px-2.5 pb-2.5 pt-2">
                        <WorkspaceTile workspace={space} size={40} />
                        <div className="min-w-0">
                            <p className="truncate text-[15px] font-semibold">{space.name}</p>
                            <p className="truncate text-[12.5px] text-muted-foreground">
                                {yours ? 'Your personal space' : space.personal ? `${space.accountName ?? 'Someone'}’s personal space` : space.accountName ? `${space.accountName}’s space` : counts}
                            </p>
                        </div>
                    </div>
                    <DropdownMenuSeparator className={SEPARATOR} />
                    {spaces && (
                        <>
                            {spaces
                                .filter((s) => s.id !== space.id)
                                .map((s) => (
                                    <DropdownMenuItem key={s.id} onSelect={() => onSpace(s.id)} className={ITEM}>
                                        <WorkspaceTile workspace={s} size={28} />
                                        <span className="min-w-0 truncate">{s.name}</span>
                                    </DropdownMenuItem>
                                ))}
                            {/* A phone has no rail: the + is here, among the spaces. */}
                            <DropdownMenuItem onSelect={onNewSpace} className={ITEM}>
                                <Plus className={ICON} strokeWidth={1.75} />
                                New space
                            </DropdownMenuItem>
                            <DropdownMenuSeparator className={SEPARATOR} />
                        </>
                    )}
                    {manages && !space.archived && (
                        <DropdownMenuItem onSelect={onInvite} className={ITEM}>
                            <UserPlus className={ICON} strokeWidth={1.75} />
                            Invite people to {space.name}
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem onSelect={() => onMembers('people')} className={ITEM}>
                        <UsersRound className={ICON} strokeWidth={1.75} />
                        Members and agents
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => onMembers('access')} className={ITEM}>
                        <KeyRound className={ICON} strokeWidth={1.75} />
                        What members can reach
                    </DropdownMenuItem>
                    {asked > 0 && (
                        <DropdownMenuItem onSelect={() => onMembers('questions')} className={ITEM}>
                            <MessageCircleQuestion className={ICON} strokeWidth={1.75} />
                            <span className="flex-1">{ASKED_TITLE}</span>
                            <span className="text-[12.5px] tabular-nums text-muted-foreground">{asked}</span>
                        </DropdownMenuItem>
                    )}
                    {((manages && !space.archived) || (space.own && !space.personal)) && <DropdownMenuSeparator className={SEPARATOR} />}
                    {manages && !space.archived && (
                        <DropdownMenuItem onSelect={onEdit} className={ITEM}>
                            <Pencil className={ICON} strokeWidth={1.75} />
                            Name and logo
                        </DropdownMenuItem>
                    )}
                    {space.own && !space.personal && (
                        <DropdownMenuItem onSelect={onSaveTemplate} className={ITEM}>
                            <LayoutTemplate className={ICON} strokeWidth={1.75} />
                            Save as template
                        </DropdownMenuItem>
                    )}
                    {!yours && <DropdownMenuSeparator className={SEPARATOR} />}
                    {yours ? null : space.own ? (
                        <>
                            {space.archived ? (
                                <DropdownMenuItem onSelect={onUnarchive} className={ITEM}>
                                    <ArchiveRestore className={ICON} strokeWidth={1.75} />
                                    Unarchive space
                                </DropdownMenuItem>
                            ) : (
                                <DropdownMenuItem onSelect={() => onAsk('archive')} className={ITEM}>
                                    <Archive className={ICON} strokeWidth={1.75} />
                                    Archive space
                                </DropdownMenuItem>
                            )}
                            <DropdownMenuItem onSelect={() => onAsk('delete')} className={DANGER}>
                                <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                                Delete space
                            </DropdownMenuItem>
                        </>
                    ) : (
                        <DropdownMenuItem onSelect={() => onAsk('leave')} className={DANGER}>
                            <LogOut className="h-4 w-4" strokeWidth={1.75} />
                            Leave {space.name}
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
            {end}
        </div>
    );
}

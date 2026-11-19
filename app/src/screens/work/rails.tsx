// Work's rails, as Slack draws them: the spaces down the left (a dot on one with something unread, an archived one
// faded, + to make one),
// then its views (Home, Agents, DMs, Resources), each an icon over its name. On a phone the views are a bar along the
// bottom instead.
import { House, Layers, MessagesSquare, Plus, UsersRound } from 'lucide-react';
import { CountBadge } from '@/ui/CountBadge';
import { SIDEBAR_CURRENT } from '@/ui/sidebarParts';
import { HAIRLINE } from '@/ui/primitives';
import { WorkspaceTile } from '@/screens/channels/workspaces';
import { ShortcutTooltip, TOOLTIP_SURFACE } from '@/ui/ShortcutTooltip';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/ui/tooltip';
import type { Intent } from '@/ui/useIntent';
import { cn } from '@/ui/utils';
import type { WorkView } from './place';
import type { WorkSpace } from './spaces';

export const VIEWS: { id: WorkView; label: string; icon: typeof House }[] = [
    { id: 'home', label: 'Home', icon: House },
    { id: 'agents', label: 'Agents', icon: UsersRound },
    { id: 'dms', label: 'DMs', icon: MessagesSquare },
    // The sidebar's Resources mark: the account's Resources, cut to the space.
    { id: 'resources', label: 'Resources', icon: Layers },
];

/** What's waiting in each view, as a count on its icon (Agents: what needs you; DMs: unread). */
export type ViewCounts = Partial<Record<WorkView, number>>;

export function SpaceRail({ spaces, current, unread, onSpace, onNew, ahead }: { spaces: WorkSpace[]; current: string; unread: (space: WorkSpace) => boolean; onSpace: (id: string) => void; onNew: () => void; ahead?: Intent }) {
    return (
        <nav aria-label="Spaces" className={cn('flex w-[68px] shrink-0 flex-col items-center gap-2.5 overflow-y-auto border-r bg-card pb-3 pt-3 scrollbar-hide dark:bg-black', HAIRLINE)}>
            {spaces.map((s) => {
                const on = s.id === current;
                return (
                    <Tooltip key={s.id}>
                        <TooltipTrigger asChild>
                            <button
                                type="button"
                                onClick={() => onSpace(s.id)}
                                {...(on ? {} : ahead?.(s.id))}
                                aria-label={s.name}
                                aria-current={on ? 'page' : undefined}
                                className={cn('relative shrink-0 rounded-[15px] p-[3px] ring-2 transition-shadow focus-visible:outline-none focus-visible:ring-ring', on ? 'ring-foreground/60' : 'ring-transparent hover:ring-foreground/15')}
                            >
                                <WorkspaceTile workspace={s} size={40} className={cn(s.archived && 'opacity-50')} />
                                {!on && unread(s) && <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full bg-foreground ring-[2.5px] ring-card dark:ring-black" data-testid="space-unread" />}
                            </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" sideOffset={8} className={TOOLTIP_SURFACE}>
                            {s.name}
                            {s.accountName && <span className="block text-muted-foreground">{s.accountName}’s</span>}
                            {s.archived && <span className="block text-muted-foreground">Archived</span>}
                        </TooltipContent>
                    </Tooltip>
                );
            })}
            <ShortcutTooltip label="New space" side="right" sideOffset={8}>
                <button
                    type="button"
                    onClick={onNew}
                    aria-label="New space"
                    // The tiles' own square, so the + reads as one more space.
                    className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                    <Plus className="h-5 w-5" strokeWidth={1.75} />
                </button>
            </ShortcutTooltip>
        </nav>
    );
}

export function ViewRail({ view, counts, onView, ahead }: { view: WorkView; counts: ViewCounts; onView: (view: WorkView) => void; ahead?: Intent }) {
    return (
        // Slack's width: "Resources" fits its column with a little air either side.
        <nav aria-label="Views" className={cn('flex w-[72px] shrink-0 flex-col items-center gap-1.5 border-r bg-card pt-3 dark:bg-black', HAIRLINE)}>
            {VIEWS.map((v) => {
                const on = view === v.id;
                const count = counts[v.id] ?? 0;
                return (
                    <button
                        key={v.id}
                        type="button"
                        onClick={() => onView(v.id)}
                        {...(on ? {} : ahead?.(v.id))}
                        aria-current={on ? 'page' : undefined}
                        className="group flex w-full flex-col items-center gap-1 py-1 focus-visible:outline-none"
                    >
                        <span
                            className={cn(
                                // The folded app sidebar's item, beside it: a rounded square, not a circle.
                                'relative grid h-10 w-10 place-items-center rounded-xl transition-colors group-focus-visible:ring-2 group-focus-visible:ring-ring',
                                on ? SIDEBAR_CURRENT : 'text-foreground/70 group-hover:bg-foreground/[0.05] group-hover:text-foreground'
                            )}
                        >
                            <v.icon className="h-[21px] w-[21px]" strokeWidth={on ? 2 : 1.7} />
                            {count > 0 && (
                                <span className="absolute -right-2.5 -top-1.5">
                                    <CountBadge count={count} />
                                </span>
                            )}
                        </span>
                        <span className={cn('whitespace-nowrap text-[11px] leading-none', on ? 'font-medium text-foreground' : 'text-muted-foreground group-hover:text-foreground')}>{v.label}</span>
                    </button>
                );
            })}
        </nav>
    );
}

/** A phone's views, along the bottom of the list. */
export function ViewBar({ view, counts, onView }: { view: WorkView; counts: ViewCounts; onView: (view: WorkView) => void }) {
    return (
        <nav aria-label="Views" className={cn('flex shrink-0 border-t bg-background py-2', HAIRLINE)}>
            {VIEWS.map((v) => {
                const on = view === v.id;
                const count = counts[v.id] ?? 0;
                return (
                    <button
                        key={v.id}
                        type="button"
                        onClick={() => onView(v.id)}
                        aria-current={on ? 'page' : undefined}
                        className={cn('flex flex-1 flex-col items-center gap-1 text-[11px]', on ? 'text-foreground' : 'text-muted-foreground')}
                    >
                        <span className="relative">
                            <v.icon className="h-[22px] w-[22px]" strokeWidth={on ? 2 : 1.6} />
                            {count > 0 && (
                                <span className="absolute -right-2.5 -top-1.5">
                                    <CountBadge count={count} />
                                </span>
                            )}
                        </span>
                        {v.label}
                    </button>
                );
            })}
        </nav>
    );
}

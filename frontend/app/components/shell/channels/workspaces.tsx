// A workspace as the page draws it, and the two ways to move between them: the
// rail down the left of the page on a laptop, as in Slack, and the menu on the
// workspace's name atop the channel list. A workspace shows its uploaded logo,
// else its initials on a tile cut from the theme. Unread messages in a
// workspace you're not in show as a dot on its tile.
import { Check, ChevronDown, Plus } from 'lucide-react';
import { HAIRLINE } from '~/components/dashboard/primitives';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/tooltip';
import { cn } from '~/lib/utils';
import { initialsFor, unreadIn } from './model';
import type { Channel, ChannelWorkspace } from './types';

// One letter sets larger than two, so "L" and "HH" fill their tiles alike.
const SIZE = {
    28: { box: 'h-7 w-7 rounded-lg', one: 'text-[14px]', two: 'text-[11.5px]' },
    40: { box: 'h-10 w-10 rounded-xl', one: 'text-[19px]', two: 'text-[15.5px]' },
    48: { box: 'h-12 w-12 rounded-[14px]', one: 'text-[23px]', two: 'text-[18.5px]' },
} as const;

export function WorkspaceTile({ workspace, size = 40, className }: { workspace: Pick<ChannelWorkspace, 'name' | 'logoUrl'>; size?: keyof typeof SIZE; className?: string }) {
    const { box, one, two } = SIZE[size];
    if (workspace.logoUrl) {
        return (
            <span aria-hidden className={cn('relative block shrink-0 overflow-hidden bg-card', box, className)}>
                <img src={workspace.logoUrl} alt="" draggable={false} className="h-full w-full object-cover" />
                {/* A hairline over the image keeps a dark logo's edge on a dark rail. */}
                <span className="pointer-events-none absolute inset-0 rounded-[inherit] ring-1 ring-inset ring-foreground/[0.1]" />
            </span>
        );
    }
    const initials = initialsFor(workspace.name);
    return (
        <span
            aria-hidden
            className={cn(
                'grid shrink-0 select-none place-items-center font-brand font-semibold leading-none text-foreground',
                'bg-card shadow-[0_1px_2px_rgba(0,0,0,0.06)] ring-1 ring-inset ring-border',
                'dark:bg-foreground/[0.1] dark:text-foreground/90 dark:shadow-[inset_0_1px_0_hsl(var(--foreground)/0.14)] dark:ring-foreground/[0.08]',
                box,
                initials.length > 1 ? cn(two, 'tracking-[-0.03em]') : one,
                className
            )}
        >
            {initials}
        </span>
    );
}

/** Something new in there: a dot where a count would sit. */
function UnreadDot() {
    return <span aria-hidden className="absolute -right-1 -top-1 h-3 w-3 rounded-full bg-foreground ring-[2.5px] ring-background" />;
}

function summary(unread: number): string {
    return unread ? `${unread} unread` : 'All caught up';
}

const key = (workspace: ChannelWorkspace) => workspace.id ?? 'home';

export function WorkspaceRail({
    workspaces,
    channels,
    active,
    onSelect,
    onAdd,
}: {
    workspaces: ChannelWorkspace[];
    channels: Channel[];
    active: ChannelWorkspace;
    onSelect: (workspace: ChannelWorkspace) => void;
    onAdd: () => void;
}) {
    return (
        <nav aria-label="Workspaces" className={cn('hidden w-[68px] shrink-0 flex-col items-center gap-3 overflow-y-auto border-r pb-4 pt-2 scrollbar-hide md:flex', HAIRLINE)}>
            {workspaces.map((workspace) => {
                const unread = unreadIn(workspace, channels);
                const current = workspace.id === active.id;
                return (
                    <Tooltip key={key(workspace)}>
                        <TooltipTrigger asChild>
                            <button
                                type="button"
                                onClick={() => onSelect(workspace)}
                                aria-label={`${workspace.name}, ${summary(unread)}`}
                                aria-current={current ? 'page' : undefined}
                                data-testid="workspace-tile"
                                className={cn(
                                    'relative shrink-0 rounded-xl ring-offset-2 ring-offset-background transition-shadow duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                                    current ? 'ring-2 ring-foreground' : 'hover:ring-2 hover:ring-foreground/20'
                                )}
                            >
                                <WorkspaceTile workspace={workspace} />
                                {!current && unread > 0 && <UnreadDot />}
                            </button>
                        </TooltipTrigger>
                        <TooltipContent side="right" sideOffset={12} className="rounded-lg px-2.5 py-1.5">
                            <p className="text-[13px] font-medium text-foreground">{workspace.name}</p>
                            <p className="text-[12px] text-muted-foreground">{summary(unread)}</p>
                        </TooltipContent>
                    </Tooltip>
                );
            })}
            <Tooltip>
                <TooltipTrigger asChild>
                    <button
                        type="button"
                        onClick={onAdd}
                        aria-label="Add a workspace"
                        data-testid="workspace-add"
                        className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-foreground/[0.05] text-muted-foreground transition-colors hover:bg-foreground/[0.09] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                        <Plus className="h-5 w-5" strokeWidth={1.75} />
                    </button>
                </TooltipTrigger>
                <TooltipContent side="right" sideOffset={12} className="rounded-lg px-2.5 py-1.5 text-[13px]">
                    Add a workspace
                </TooltipContent>
            </Tooltip>
        </nav>
    );
}

/** The workspace's name atop the channel list; on a phone, with its tile, the way to switch. */
export function WorkspaceSwitcher({
    workspace,
    workspaces,
    channels,
    onSelect,
    onAdd,
}: {
    workspace: ChannelWorkspace;
    workspaces: ChannelWorkspace[];
    channels: Channel[];
    onSelect: (workspace: ChannelWorkspace) => void;
    onAdd: () => void;
}) {
    const elsewhere = workspaces.some((w) => w.id !== workspace.id && unreadIn(w, channels) > 0);
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                data-testid="workspace-switcher"
                className="-ml-1 flex min-w-0 items-center gap-2.5 rounded-xl py-1 pl-1 pr-2 text-left transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] md:gap-1.5 md:pl-1.5"
            >
                <span className="relative shrink-0 md:hidden">
                    <WorkspaceTile workspace={workspace} size={28} />
                    {elsewhere && <UnreadDot />}
                </span>
                <span className="truncate font-brand text-[18px] font-semibold tracking-[-0.015em] text-foreground md:text-[17px]">{workspace.name}</span>
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                {elsewhere && <span className="sr-only">Another workspace has unread messages</span>}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" sideOffset={6} className="w-[280px] rounded-2xl p-1.5">
                {workspaces.map((w) => {
                    const unread = unreadIn(w, channels);
                    const current = w.id === workspace.id;
                    return (
                        <DropdownMenuItem key={key(w)} onSelect={() => onSelect(w)} className="gap-3 rounded-xl px-2 py-2">
                            <WorkspaceTile workspace={w} size={28} />
                            <span className="min-w-0 flex-1">
                                <span className="block truncate text-[14.5px] text-foreground">{w.name}</span>
                                <span className="block truncate text-[12.5px] text-muted-foreground">{summary(unread)}</span>
                            </span>
                            {current ? (
                                <Check className="h-4 w-4 shrink-0 text-foreground" strokeWidth={2} />
                            ) : unread ? (
                                <span aria-hidden className="mr-1.5 h-2 w-2 shrink-0 rounded-full bg-foreground/70" />
                            ) : null}
                        </DropdownMenuItem>
                    );
                })}
                <DropdownMenuSeparator className="mx-1.5 bg-border dark:bg-foreground/[0.08]" />
                <DropdownMenuItem onSelect={onAdd} className="gap-3 rounded-xl px-2 py-2 text-[14.5px]">
                    <span className="grid h-7 w-7 place-items-center rounded-lg bg-foreground/[0.06]">
                        <Plus className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
                    </span>
                    Add a workspace
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

// The channel list: the workspace's name (the way to switch on a phone), its
// agents' faces, then its channels and the way to start one. Unread channels
// read bold with a count until opened.
import { Hash, Plus } from 'lucide-react';
import type { AccountMenuUser } from '~/components/nav/AccountMenu';
import { HAIRLINE } from '~/components/dashboard/primitives';
import { cn } from '~/lib/utils';
import { Facepile } from './avatars';
import { agentKey, channelsIn } from './model';
import type { Channel, ChannelMember, ChannelWorkspace } from './types';
import { WorkspaceSwitcher } from './workspaces';

export function ChannelList({
    workspace,
    workspaces,
    channels,
    activeId,
    user,
    onSelect,
    onSwitchWorkspace,
    onAddWorkspace,
    onNewChannel,
    className,
}: {
    workspace: ChannelWorkspace;
    workspaces: ChannelWorkspace[];
    /** Every channel the account has; the list keeps this workspace's. */
    channels: Channel[];
    activeId: string | null;
    user: AccountMenuUser;
    onSelect: (id: string) => void;
    onSwitchWorkspace: (workspace: ChannelWorkspace) => void;
    onAddWorkspace: () => void;
    onNewChannel: () => void;
    className?: string;
}) {
    const mine = channelsIn(workspace, channels);
    const agents = new Map<string, ChannelMember>();
    for (const channel of mine)
        for (const m of channel.members) {
            const key = agentKey(m);
            if (m.kind === 'agent' && key && !agents.has(key)) agents.set(key, m);
        }
    const faces = [...agents.values()];

    return (
        <nav aria-label="Channels" className={cn('shrink-0 flex-col overflow-y-auto px-2 pb-6 scrollbar-subtle md:w-[var(--channel-list-width,260px)] md:border-r', HAIRLINE, className)}>
            <div className="flex h-14 shrink-0 items-center justify-between gap-2 px-1.5 md:px-1">
                <WorkspaceSwitcher workspace={workspace} workspaces={workspaces} channels={channels} onSelect={onSwitchWorkspace} onAdd={onAddWorkspace} />
            </div>
            <div className="group/header flex h-8 w-full items-center gap-1.5 px-2.5">
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-muted-foreground">Channels</span>
                {faces.length > 0 && (
                    <span title={faces.map((a) => a.name).join(', ')}>
                        <Facepile members={faces.slice(0, 4)} user={user} size={16} />
                    </span>
                )}
                <button
                    type="button"
                    onClick={onNewChannel}
                    aria-label="New channel"
                    data-testid="new-channel"
                    className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                    <Plus className="h-4 w-4" strokeWidth={2} />
                </button>
            </div>
            {mine.length ? (
                <ul className="mt-0.5 flex flex-col gap-px">
                    {mine.map((ch) => {
                        const current = ch.id === activeId;
                        const unread = current ? 0 : ch.unread;
                        return (
                            <li key={ch.id}>
                                <button
                                    type="button"
                                    onClick={() => onSelect(ch.id)}
                                    aria-current={current ? 'page' : undefined}
                                    className={cn(
                                        'flex h-10 w-full items-center gap-2 rounded-lg pl-2.5 pr-2 text-[15px] transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring md:h-8 md:text-[14px]',
                                        unread ? 'font-semibold text-foreground' : 'text-foreground/65 hover:text-foreground',
                                        current && 'md:bg-foreground/[0.07] md:font-medium md:text-foreground md:hover:bg-foreground/[0.07]'
                                    )}
                                >
                                    <Hash className={cn('h-4 w-4 shrink-0', unread || current ? 'text-foreground/70' : 'text-muted-foreground/60')} strokeWidth={1.75} />
                                    <span className="min-w-0 flex-1 truncate text-left">{ch.name}</span>
                                    {unread > 0 && (
                                        <span className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-foreground px-1.5 text-[11px] font-semibold tabular-nums leading-none text-background">
                                            {unread > 99 ? '99+' : unread}
                                        </span>
                                    )}
                                </button>
                            </li>
                        );
                    })}
                </ul>
            ) : (
                <button
                    type="button"
                    onClick={onNewChannel}
                    className="mx-1 mt-1 flex w-[calc(100%-8px)] items-center gap-2 rounded-lg px-1.5 py-2 text-left text-[14px] text-muted-foreground transition-colors hover:bg-foreground/[0.04] hover:text-foreground"
                >
                    <Plus className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                    Start a channel
                </button>
            )}
        </nav>
    );
}

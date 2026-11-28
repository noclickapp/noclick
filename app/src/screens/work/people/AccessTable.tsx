// What a space's people can reach: each resource linked to the space, at the level its members and its guests have.
// Agents reach more than people do: "through agents only" lets a member ask an agent to use it, not open it.
import type { ReactNode } from 'react';
import { HAIRLINE } from '@/ui/primitives';
import { Skeleton } from '@/ui/skeleton';
import { cn } from '@/ui/utils';
import { useWorkFrames } from '@/sdk/live';
import { useWorkPlace } from '../place';
import { kindOf, LINK_KIND, readSpaceAgain, thingKey, useSpaceLinks, type LinkKind, type SpaceKind, type SpaceLink } from '../resources/space/data';
import { LevelMenu } from '../resources/space/parts';
import type { WorkSpace } from '../spaces';

const spaceKindOf = (kind: LinkKind) => (Object.entries(LINK_KIND).find(([, k]) => k === kind)?.[0] ?? null) as SpaceKind | null;

export function AccessTable({ space, manages }: { space: WorkSpace; manages: boolean }) {
    return (
        <div className="px-3 py-2" data-testid="access-table">
            <p className={cn('border-b pb-2 text-[12.5px] leading-snug text-muted-foreground', HAIRLINE)}>What {space.name} shares, and what its members and its guests get of each.</p>
            <Links spaceId={space.workspaceId} manages={manages} />
        </div>
    );
}

function Links({ spaceId, manages }: { spaceId: string; manages: boolean }) {
    const links = useSpaceLinks(spaceId);
    const [, go] = useWorkPlace();
    useWorkFrames('platform:resource', (frame) => {
        if ((frame.kind as string) === 'workspace_resource' && frame.parent_id === spaceId) readSpaceAgain(spaceId);
    });
    if (links.loading) {
        return (
            <div className="space-y-3 pt-3" aria-busy>
                <Skeleton className="h-8 w-full rounded-full" />
                <Skeleton className="h-8 w-full rounded-full" />
            </div>
        );
    }
    if (!links.data) return <Note>What this space shares couldn’t be read. It’s read again when you come back.</Note>;
    if (!links.data.length) return <Note>Nothing is shared with this space yet. Share a repo, a database or a connection with it from Resources, and choose here what its members and guests get.</Note>;
    const open = (link: SpaceLink) => {
        const kind = spaceKindOf(link.kind);
        if (kind) go({ view: 'resources', res: kind, item: thingKey(kind, link.ref), panel: null });
    };
    return (
        <ul className="divide-y divide-border/60">
            {links.data.map((link) => {
                const kind = spaceKindOf(link.kind);
                const Icon = kind ? kindOf(kind).icon : null;
                return (
                    <li key={link.id} className="py-2.5" data-link={link.id}>
                        <button type="button" onClick={() => open(link)} className="flex max-w-full items-center gap-2 rounded-full py-1 text-left text-[14px] font-medium text-foreground hover:underline">
                            {Icon && <Icon className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />}
                            <span className="truncate">{link.name}</span>
                        </button>
                        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-2 pl-6">
                            {(['members', 'guests'] as const).map((who) => (
                                <span key={who} className="flex min-w-0 items-center gap-2">
                                    <span className="text-[12.5px] text-muted-foreground">{who === 'members' ? 'Members' : 'Guests'}</span>
                                    <LevelMenu spaceId={spaceId} link={link} who={who} readOnly={!manages} />
                                </span>
                            ))}
                        </div>
                    </li>
                );
            })}
        </ul>
    );
}

function Note({ children }: { children: ReactNode }) {
    return <p className="pt-4 text-[13px] leading-relaxed text-muted-foreground">{children}</p>;
}

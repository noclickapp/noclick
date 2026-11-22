// A space's Resources tab: everything the space's people and agents can use, in one place. The list column names
// each kind with how many the space has (machines: how many are up); the main pane is the overview, a kind's list or
// an item's page, each made, added, renamed, shared, removed or deleted from here. It's the space's view of what it
// can use, never a second owner: the account's Resources page owns each one. Where you are is the URL's (`res`,
// `item`), and what moves is followed from the backend's frames. Home's tab (`HOME_SPACE`) is the same, for its agents
// in no space and what the account has for them: nothing in it is shared with people, and each item can be shared with
// a space from its menu.
import { useMemo, useState, type ReactNode } from 'react';
import { LayoutGrid, type LucideIcon } from 'lucide-react';
import { invalidateV1 } from '@/sdk/useV1';
import { staleReads } from '@/sdk/staleReads';
import type { NoClick } from 'noclick';
import { HAIRLINE } from '@/ui/primitives';
import { useInPhoneShell } from '@/ui/phoneBar';
import { createPanelWidth } from '@/ui/panelWidth';
import { ResizeEdge } from '@/ui/ResizeEdge';
import { resourceAddress, type KindId } from '@/screens/resources/kinds';
import { refFor } from '@/lib/agentTools';
import { Skeleton } from '@/ui/skeleton';
import { useWork } from '../context';
import { cn } from '@/ui/utils';
import { useAgentFrames } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';
import { useWorkNav } from '../nav';
import { RES_OVERVIEW, useWorkPlace } from '../place';
import { useKnowledgeFrames } from './knowledge/store';
import { renameThing } from './space/actions';
import { GROUPS, isSpaceKind, KINDS, readSpaceAgain, SPACES_KEY, useConnections, useSpaceShare, type SpaceKind, type Thing } from './space/data';
import { AddDialog, CreateDialog, DeleteDialog, ShareDialog } from './space/dialogs';
import { ItemPage } from './space/ItemPage';
import { KindPage } from './space/KindPage';
import { Overview } from './space/Overview';
import { Crumbs } from './space/parts';
import type { Dialog, Pane, SpaceAt } from './space/pane';

export type { SpaceAt } from './space/pane';

/** The tab's list column: as wide as Work's other lists, remembered with them. */
const COLUMN = createPanelWidth({ key: 'nc-work-list', initial: 280, min: 220, max: 420 });

/** Where the tab is, as the URL keeps it: a kind (`res`) and one of its items (`item`). */
function useAt(): [SpaceAt, (at: SpaceAt) => void] {
    const [place, go] = useWorkPlace();
    const at: SpaceAt = isSpaceKind(place.res) ? { kind: place.res, item: place.item ?? undefined } : null;
    return [at, (next) => go({ res: next?.kind ?? null, item: next?.item ?? null })];
}

/** Everything the space shows reads again when the backend says something it holds moved. */
function useSpaceFrames(spaceId: string): void {
    useKnowledgeFrames();
    useAgentFrames();
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'workspace_resource') {
            if (frame.parent_id === spaceId) readSpaceAgain(spaceId);
            return;
        }
        for (const prefix of staleReads(frame)) invalidateV1(prefix);
        // A skill, memory or machine moving changes the space's counts too.
        if (frame.kind === 'skill' || frame.kind === 'memory' || frame.kind === 'machine' || frame.kind === 'sandbox') readSpaceAgain(spaceId);
    });
    useWorkFrames('platform:coding_agent', () => readSpaceAgain(spaceId));
    useWorkFrames('platform:channel', (frame) => {
        if (frame.kind === 'workspace' || frame.kind === 'channel') {
            readSpaceAgain(spaceId);
            invalidateV1(SPACES_KEY);
        }
    });
}

function usePane(spaceId: string): Pane & { dialog: Dialog; setDialog: (d: Dialog) => void; at: SpaceAt } {
    const nav = useWorkNav();
    const { openPage } = useWork();
    const share = useSpaceShare(spaceId);
    const connectionsRead = useConnections();
    const [at, onAt] = useAt();
    const [dialog, setDialog] = useState<Dialog>(null);
    // A space names a connection by its id or its ref: a named one's name, never an app account's.
    const connections = useMemo(() => new Map((connectionsRead.data ?? []).flatMap((c) => [[c.id, c] as const, [refFor(c), c] as const])), [connectionsRead.data]);
    return {
        spaceId,
        share,
        connections,
        now: new Date().toISOString(),
        at,
        onAt,
        dialog,
        setDialog,
        open: (t: Thing) => (t.kind === 'agents' ? nav.openProfile(t.ref) : onAt({ kind: t.kind, item: t.key })),
        ask: (d: Dialog) => (d?.kind === 'create' && d.of === 'agents' ? nav.newAgent() : setDialog(d)),
        rename: (client: NoClick, t: Thing, name: string) => renameThing(client, spaceId, t, name),
        accountPage: openPage && ((kind: KindId | null, resource?: string) => openPage('resources', resourceAddress(kind, { resource }))),
    };
}

const LIST_ROW =
    'flex w-full items-center gap-2.5 rounded-lg pl-2.5 pr-2 max-md:pl-2 text-left transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';
const LIST_CURRENT = 'bg-foreground/[0.07] hover:bg-foreground/[0.07]';

/** The list column on the Resources tab: the overview, then each kind with how many the space has. A kind stays
 *  picked while one of its items is open. */
export function SpaceResourcesNav({ spaceId }: { spaceId: string }) {
    const share = useSpaceShare(spaceId);
    const connections = useConnections();
    const [at, onAt] = useAt();
    const [, go] = useWorkPlace();
    // A phone shows this list alone, so nothing in it is open, and the overview opens over it as the kinds do.
    const phone = useInPhoneShell();
    const broken = new Set((connections.data ?? []).filter((c) => c.status === 'disconnected').flatMap((c) => [c.id, refFor(c)]));
    const row = (current: boolean, icon: LucideIcon, label: string, figure: ReactNode, onClick: () => void) => {
        const Icon = icon;
        return (
            <button
                type="button"
                onClick={onClick}
                aria-current={current ? 'page' : undefined}
                className={cn(LIST_ROW, 'h-8 text-[14px] max-md:h-10 max-md:text-[16px]', current ? cn(LIST_CURRENT, 'font-medium text-foreground') : 'text-foreground/75 hover:text-foreground')}
            >
                <Icon className="h-4 w-4 shrink-0 text-foreground/70" strokeWidth={1.75} />
                <span className="min-w-0 flex-1 truncate">{label}</span>
                {figure}
            </button>
        );
    };
    const figure = (k: SpaceKind) => {
        if (!share.summary) return <Skeleton className="h-3 w-4 rounded" />;
        if (k === 'machines') return <span className="text-[12.5px] tabular-nums text-muted-foreground">{share.up.sandboxes + share.up.keptOn + share.up.own} up</span>;
        const n = share.of(k).length;
        const hurt = k === 'connections' && share.of(k).some((t) => broken.has(t.ref));
        return (
            <span className="flex items-center gap-1.5 text-[12.5px] tabular-nums text-muted-foreground">
                {hurt && <span className="h-1.5 w-1.5 rounded-full bg-red-500" aria-label="One isn’t working" />}
                {n || <span className="text-muted-foreground/60">0</span>}
            </span>
        );
    };
    return (
        <nav aria-label={share.home ? 'Your resources' : `${share.spaceName || 'This space'}’s resources`} className="flex flex-col gap-px" data-testid="space-resources-nav">
            {row(!phone && at === null, LayoutGrid, 'Overview', null, () => (phone ? go({ res: RES_OVERVIEW, item: null }) : onAt(null)))}
            {(Object.keys(GROUPS) as (keyof typeof GROUPS)[]).map((g) => {
                const kinds = KINDS.filter((k) => k.group === g && share.kinds.includes(k.id));
                return (
                    <div key={g} className="mt-3 flex flex-col gap-px">
                        <p className="flex h-8 items-center px-2.5 pt-1 text-[13px] font-medium text-muted-foreground max-md:px-2">{GROUPS[g]}</p>
                        {kinds.map((k) => (
                            <div key={k.id}>{row(at?.kind === k.id, k.icon, k.label, figure(k.id), () => onAt({ kind: k.id }))}</div>
                        ))}
                    </div>
                );
            })}
        </nav>
    );
}

/** The main pane on the Resources tab: the overview, a kind's list, or an item's page. */
export function SpaceResourcesPane({ spaceId }: { spaceId: string }) {
    useSpaceFrames(spaceId);
    const pane = usePane(spaceId);
    const { at, share, dialog, setDialog } = pane;
    const item = at?.item ? share.find(at.item) : undefined;
    const knowledge = item && (item.kind === 'skills' || item.kind === 'memories');
    const close = () => setDialog(null);
    let body: ReactNode;
    if (share.loading) {
        body = (
            <div className="space-y-4" aria-busy>
                <Skeleton className="h-10 w-48 rounded-full" />
                <div className="grid gap-2.5 @2xl:grid-cols-2">
                    <Skeleton className="h-44 rounded-[20px]" />
                    <Skeleton className="h-44 rounded-[20px]" />
                </div>
            </div>
        );
    } else if (share.error !== undefined && !share.summary) {
        body = <p className="py-10 text-[14px] text-muted-foreground">{share.home ? 'Your' : 'This space’s'} resources couldn’t be read. They’re read again when you come back to this tab.</p>;
    } else if (at === null) body = <Overview {...pane} />;
    else if (at.item)
        body = item ? (
            <ItemPage key={item.key} {...pane} t={item} />
        ) : (
            <>
                <Crumbs onAt={pane.onAt} kind={at.kind} />
                <p className="py-10 text-[14px] text-muted-foreground">{share.home ? 'It’s gone: it was deleted.' : 'It’s gone: it was deleted or taken out of this space.'}</p>
            </>
        );
    else body = <KindPage key={at.kind} kind={at.kind} {...pane} />;
    const deleting = dialog?.kind === 'delete' ? share.find(dialog.key) : undefined;
    const sharing = dialog?.kind === 'share' ? share.find(dialog.key) : undefined;
    return (
        <div className="@container min-h-0 flex-1 overflow-y-auto scrollbar-subtle" data-testid="space-resources">
            <div className={cn('mx-auto w-full max-w-[1040px] pb-20', knowledge ? 'pt-4' : 'px-5 pt-6 @2xl:px-10 @2xl:pt-10')}>{body}</div>
            {dialog?.kind === 'add' && <AddDialog {...pane} kind={dialog.of} onClose={close} />}
            {dialog?.kind === 'create' && <CreateDialog {...pane} kind={dialog.of} onClose={close} />}
            {deleting && <DeleteDialog {...pane} t={deleting} onClose={close} />}
            {sharing && <ShareDialog {...pane} t={sharing} onClose={close} />}
        </div>
    );
}

/** The tab whole: the kinds in a column of their own beside the pane (the pane alone in a narrow window, where the
 *  overview's tiles lead to every kind). */
export function SpaceResources({ spaceId }: { spaceId: string }) {
    const width = COLUMN.useWidth();
    return (
        <div className="flex min-h-0 min-w-0 flex-1">
            <aside className={cn('relative hidden shrink-0 flex-col border-r md:flex', HAIRLINE)} style={{ width }}>
                <ResizeEdge panel={COLUMN} label="Resize the list" />
                <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-6 pt-3 scrollbar-subtle">
                    <SpaceResourcesNav spaceId={spaceId} />
                </div>
            </aside>
            <section className="flex min-w-0 flex-1 flex-col">
                <SpaceResourcesPane spaceId={spaceId} />
            </section>
        </div>
    );
}

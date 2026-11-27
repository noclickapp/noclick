// Home's list, as Slack's: find a conversation, the threads you follow, NoClick's template gallery (in a space you can
// add one to), the channels you starred, your own sections of
// the space's channels, then the rest under Channels and + to start one. A channel is bold with a count where
// something's unread, and an @ count where something @-mentions you; one you muted is quiet (dim, never bold, a
// bell-off) until something mentions you; a closed one is dim behind a lock, after the open ones. With none yet while
// they're `loading` (read, or the personal space's NoClick channel still on its way), its rows are grey shapes: never a
// list saying it has nothing.
//
// Your sections are yours alone and follow you to every device (useChannelSections): you make, name, rename, reorder
// and delete them (a deleted one's channels go back to Channels), and move a channel into one by dragging it or from
// its row's menu, which a keyboard and a phone reach too. Starred, each section and Channels fold on their own;
// folded, a list still shows the channels with something for you and the one that's open.
import { useState, type DragEvent } from 'react';
import { BellOff, Hash, LayoutTemplate, Lock, MessageSquareText, Search } from 'lucide-react';
import { toast } from 'sonner';
import { useInPhoneShell } from '@/ui/phoneBar';
import type { Channel } from '@/screens/channels/types';
import type { Intent } from '@/ui/useIntent';
import { useWork } from '../context';
import { cn } from '@/ui/utils';
import { TEMPLATES, THREADS } from '../place';
import { searchTextClass } from '@/ui/SearchField';
import { Count, FIND_PILL, LIST_CURRENT, LIST_ROW, MentionCount } from '../ui';
import { DropLine, FoldHeader, lowerHalf, MoveMenu, SectionNameField, useDrag, usePressAndHold, type Dragged, type DropAt } from './SectionParts';
import {
    addSection,
    groupChannels,
    isFolded,
    moveChannel,
    moveSection,
    removeSection,
    renameSection,
    restoreSection,
    sectionOf,
    setFolded,
    shownFolded,
    type Destination,
    type Section,
} from './sections';
import { useChannelSections } from './useChannelSections';

const STARRED = 'starred';
const CHANNELS = 'channels';

/** Where a section is being named: a new one (for a channel to go into, when one asked), or one being renamed. */
type Naming = { kind: 'new'; channelId?: string } | { kind: 'rename'; id: string };

const newId = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now().toString(16)}-0000-4000-8000-${Math.random().toString(16).slice(2, 14).padEnd(12, '0')}`);

export function HomeList({
    channels,
    workspaceId,
    loading = false,
    openId,
    threads,
    templates = false,
    onOpen,
    onNewChannel,
    onStar,
    ahead,
}: {
    /** The space's channels, oldest first. */
    channels: Channel[];
    /** The space's workspace, whose channels your sections group (null: your channels in no workspace). */
    workspaceId: string | null;
    /** More are on their way (the first read, or a channel being made): with none yet, it waits rather than says so. */
    loading?: boolean;
    /** What's open: a channel's id, `THREADS` or `TEMPLATES`. */
    openId: string | null;
    /** Threads you follow with replies you haven't read; null where threads aren't read. */
    threads: number | null;
    /** Whether the space lists its template gallery (where you can add one: a space of your own). */
    templates?: boolean;
    onOpen: (id: string) => void;
    onNewChannel: (() => void) | null;
    /** Star a channel for yourself, or take its star off: a starred one moved into a section loses its star. */
    onStar: (channelId: string, on: boolean) => Promise<unknown>;
    /** Reads ahead the channel a row the pointer rests on opens. */
    ahead?: Intent;
}) {
    const phone = useInPhoneShell();
    const { layout, change } = useChannelSections(workspaceId);
    const [naming, setNaming] = useState<Naming | null>(null);
    const [menuFor, setMenuFor] = useState<string | null>(null);
    const grouped = groupChannels(channels, layout);
    const byId = new Map(channels.map((c) => [c.id, c]));

    const star = (id: string, on: boolean) => {
        const ch = byId.get(id);
        onStar(id, on).catch((e: unknown) => toast.error(`Couldn’t ${on ? 'star' : 'unstar'} #${ch?.name ?? 'the channel'}`, { description: e instanceof Error ? e.message : undefined }));
    };
    /** Into a section (null: Channels) at `index` among its channels; Starred stars it instead. `made`: into a section
     *  made just now, which the layout drawn doesn't hold yet. */
    const move = (id: string, to: Destination | typeof STARRED, index?: number, made = false) => {
        const ch = byId.get(id);
        const moved = moveChannel(id, to === STARRED ? null : to, index);
        // Only a change that moves something is saved.
        if (made || JSON.stringify(moved(layout).sections) !== JSON.stringify(layout.sections)) change(moved);
        // Starred wins where it shows, so a starred channel moved elsewhere leaves Starred, and one dropped there stars.
        if (to === STARRED ? !ch?.starred : ch?.starred) star(id, to === STARRED);
    };
    const fold = (key: string) => change(setFolded(key, !isFolded(layout, key)));
    const deleteSection = (section: Section) => {
        const index = layout.sections.findIndex((s) => s.id === section.id);
        change(removeSection(section.id));
        toast(`Deleted ${section.name}`, {
            description: section.channelIds.length ? 'Its channels are back in Channels.' : undefined,
            action: { label: 'Undo', onClick: () => change(restoreSection(section, index)) },
        });
    };
    const named = (name: string) => {
        if (naming?.kind === 'rename') change(renameSection(naming.id, name));
        else if (naming?.kind === 'new') {
            const id = newId();
            change(addSection(id, name));
            if (naming.channelId) move(naming.channelId, id, undefined, true);
        }
        setNaming(null);
    };

    const hold = usePressAndHold(setMenuFor);
    const drag = useDrag((d: Dragged, at: DropAt) => (d.kind === 'channel' ? true : at.list !== STARRED && at.list !== CHANNELS));
    const itemsOf = (list: string) => (list === CHANNELS ? grouped.rest : list === STARRED ? grouped.starred : (grouped.sections.find((g) => g.section.id === list)?.channels ?? []));
    const onDrop = (e: DragEvent) => {
        const { dragged, over } = drag;
        drag.end();
        if (!dragged || !over) return;
        e.preventDefault();
        if (dragged.kind === 'section') {
            // Before (0) or after (1) the section it's dropped on, among the others.
            const others = layout.sections.filter((s) => s.id !== dragged.id);
            const target = others.findIndex((s) => s.id === over.list);
            if (target >= 0) change(moveSection(dragged.id, target + over.index));
            return;
        }
        if (over.list === STARRED || over.list === CHANNELS) return move(dragged.id, over.list === STARRED ? STARRED : null);
        // Before the first row from the drop on that isn't the one dragged, by that row's place in the section's own
        // order (which may hold channels it doesn't show); at the end past them all.
        const ids = (layout.sections.find((s) => s.id === over.list)?.channelIds ?? []).filter((x) => x !== dragged.id);
        const before = itemsOf(over.list)
            .slice(over.index)
            .find((c) => c.id !== dragged.id);
        move(dragged.id, over.list, before ? ids.indexOf(before.id) : ids.length);
    };
    /** A list's drop handlers: over a row, before or after it by the pointer; past the rows, at the end. */
    const dropZone = (list: string, count: number) =>
        phone
            ? {}
            : {
                  onDragOver: (e: DragEvent) => {
                      const row = (e.target as Element).closest?.('li[data-index]');
                      const index = row ? Number(row.getAttribute('data-index')) + (lowerHalf(e, row) ? 1 : 0) : count;
                      drag.hover(e, { list, index: drag.dragged?.kind === 'section' ? Number(lowerHalf(e, e.currentTarget)) : index });
                  },
                  onDrop,
              };

    const row = (ch: Channel, list: string, index: number) => {
        const on = ch.id === openId;
        const closed = ch.status === 'closed';
        const mentions = ch.mentions ?? 0;
        const loud = !closed && (ch.muted ? mentions > 0 : ch.unread > 0);
        const dropping = drag.dragged?.kind === 'channel' && drag.over?.list === list;
        return (
            <li
                key={ch.id}
                data-index={index}
                data-channel={ch.id}
                className="group/row relative select-none [-webkit-touch-callout:none]"
                {...(phone ? hold(ch.id) : {})}
                draggable={!phone}
                onDragStart={(e) => drag.start(e, { kind: 'channel', id: ch.id })}
                onDragEnd={drag.end}
                onContextMenu={(e) => {
                    e.preventDefault();
                    setMenuFor(ch.id);
                }}
            >
                <button
                    type="button"
                    onClick={() => onOpen(ch.id)}
                    {...ahead?.(ch.id)}
                    aria-current={on ? 'page' : undefined}
                    data-muted={ch.muted || undefined}
                    className={cn(
                        LIST_ROW,
                        'h-8 pl-2.5 text-[14px] max-md:h-10 max-md:pl-2 max-md:text-[16px]',
                        on ? cn(LIST_CURRENT, 'font-medium text-foreground') : loud ? 'font-semibold text-foreground' : ch.muted || closed ? 'text-foreground/40 hover:text-foreground/70' : 'text-foreground/65 hover:text-foreground',
                        drag.dragged?.id === ch.id && 'opacity-50'
                    )}
                >
                    {closed ? (
                        <Lock aria-label="Closed" className="h-3.5 w-4 shrink-0 text-muted-foreground/60" strokeWidth={1.9} />
                    ) : (
                        <Hash className={cn('h-4 w-4 shrink-0', loud || on ? 'text-foreground/70' : 'text-muted-foreground/60')} strokeWidth={1.75} />
                    )}
                    <span className="min-w-0 flex-1 truncate">{ch.name}</span>
                    {/* The counts make way for the row's menu while it's shown. */}
                    <span className={cn('flex shrink-0 items-center gap-1.5 transition-opacity', !phone && 'group-focus-within/row:opacity-0 group-hover/row:opacity-0')}>
                        {ch.muted && <BellOff aria-label="Muted" className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" strokeWidth={1.9} />}
                        {!on && !closed && mentions > 0 && <MentionCount n={mentions} />}
                        {/* Muted, all it counts as unread is what mentions you. */}
                        {loud && !on && !ch.muted && <Count n={ch.unread} />}
                    </span>
                </button>
                <MoveMenu
                    name={ch.name}
                    sections={layout.sections}
                    current={sectionOf(layout, ch.id)?.id ?? null}
                    open={menuFor === ch.id}
                    onOpenChange={(o) => setMenuFor(o ? ch.id : null)}
                    onMove={(to) => move(ch.id, to)}
                    onNewSection={() => setNaming({ kind: 'new', channelId: ch.id })}
                />
                {dropping && drag.over?.index === index && <DropLine at="top" />}
                {dropping && drag.over?.index === index + 1 && <DropLine at="bottom" />}
            </li>
        );
    };

    /** A foldable list under its header: folded, only the channels with something for you and the one that's open. */
    const list = (key: string, label: string, items: Channel[], extra: Partial<Parameters<typeof FoldHeader>[0]> = {}, testId?: string) => {
        const folded = isFolded(layout, key);
        const shown = folded ? shownFolded(items, openId) : items;
        const section = layout.sections.find((s) => s.id === key);
        const dropping = !!drag.dragged && drag.over?.list === key;
        return (
            <div key={key} data-list={key} className="relative mb-2" {...dropZone(key, items.length)}>
                {naming?.kind === 'rename' && naming.id === key ? (
                    <SectionNameField initial={label} onDone={named} onCancel={() => setNaming(null)} />
                ) : (
                    <FoldHeader
                        label={label}
                        listId={`home-list-${key}`}
                        folded={folded}
                        onFold={() => fold(key)}
                        drop={dropping && drag.dragged?.kind === 'channel' && (folded || !items.length)}
                        dragName={section && !phone ? (e) => drag.start(e, { kind: 'section', id: key }) : undefined}
                        {...extra}
                    />
                )}
                {drag.dragged?.kind === 'section' && dropping && <DropLine at={drag.over?.index ? 'bottom' : 'top'} />}
                <ul id={`home-list-${key}`} className="flex flex-col gap-px" data-testid={testId} data-folded={folded || undefined}>
                    {shown.map((c) => row(c, key, items.indexOf(c)))}
                </ul>
                {section && !folded && !items.length && <p className="pb-1 pl-[38px] pt-0.5 text-[12.5px] text-muted-foreground/80">{phone ? 'Hold a channel to move it here.' : 'Drag a channel here.'}</p>}
            </div>
        );
    };

    const { palette } = useWork();
    const sectionMenu = (section: Section, index: number) => ({
        onRename: () => setNaming({ kind: 'rename', id: section.id }),
        onMoveUp: index > 0 ? () => change(moveSection(section.id, index - 1)) : null,
        onMoveDown: index < layout.sections.length - 1 ? () => change(moveSection(section.id, index + 1)) : null,
        onNewSection: () => setNaming({ kind: 'new' }),
        onDelete: () => deleteSection(section),
    });

    return (
        <>
            {palette && (
                <button type="button" onClick={() => palette.open()} className={cn(FIND_PILL, searchTextClass('md'), 'pr-3 text-left')}>
                    <Search className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                    Find a conversation…
                </button>
            )}
            {threads !== null && (
                <button
                    type="button"
                    onClick={() => onOpen(THREADS)}
                    aria-current={openId === THREADS ? 'page' : undefined}
                    className={cn(LIST_ROW, 'h-8 pl-2.5 text-[14px] max-md:h-10 max-md:pl-2 max-md:text-[16px]', openId === THREADS ? cn(LIST_CURRENT, 'font-medium text-foreground') : threads ? 'font-semibold text-foreground' : 'text-foreground/75 hover:text-foreground')}
                >
                    <MessageSquareText className="h-4 w-4 shrink-0 text-foreground/70" strokeWidth={1.75} />
                    <span className="min-w-0 flex-1 truncate">Threads</span>
                    {threads > 0 && openId !== THREADS && <Count n={threads} />}
                </button>
            )}
            {templates && (
                <button
                    type="button"
                    onClick={() => onOpen(TEMPLATES)}
                    aria-current={openId === TEMPLATES ? 'page' : undefined}
                    data-testid="home-templates"
                    className={cn(LIST_ROW, 'h-8 pl-2.5 text-[14px] max-md:h-10 max-md:pl-2 max-md:text-[16px]', openId === TEMPLATES ? cn(LIST_CURRENT, 'font-medium text-foreground') : 'text-foreground/75 hover:text-foreground')}
                >
                    <LayoutTemplate className="h-4 w-4 shrink-0 text-foreground/70" strokeWidth={1.75} />
                    <span className="min-w-0 flex-1 truncate">Templates</span>
                </button>
            )}
            <div className="h-3" />
            {grouped.starred.length > 0 && list(STARRED, 'Starred', grouped.starred, {}, 'starred-channels')}
            {grouped.sections.map(({ section, channels: held }, i) => list(section.id, section.name, held, { menu: sectionMenu(section, i) }, 'home-section'))}
            {naming?.kind === 'new' && (
                <div className="mb-2">
                    <SectionNameField onDone={named} onCancel={() => setNaming(null)} />
                </div>
            )}
            {loading && !channels.length ? (
                <>
                    <FoldHeader label="Channels" listId="home-list-channels" folded={false} onFold={() => fold(CHANNELS)} onAdd={onNewChannel ?? undefined} addLabel="Create a channel" />
                    <ul className="flex flex-col gap-px" aria-busy data-testid="home-channels-loading">
                        {[0, 1].map((i) => (
                            <li key={i} className="h-8 animate-pulse rounded-lg bg-foreground/[0.04]" />
                        ))}
                    </ul>
                </>
            ) : (
                <>
                    {list(CHANNELS, 'Channels', grouped.rest, { menu: { onNewSection: () => setNaming({ kind: 'new' }) }, onAdd: onNewChannel ?? undefined, addLabel: 'Create a channel' }, 'home-channels')}
                    {!channels.length && <p className="px-2.5 pt-1 text-[13px] leading-snug text-muted-foreground">No channels here yet.</p>}
                </>
            )}
        </>
    );
}

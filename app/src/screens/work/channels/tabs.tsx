// A channel's tabs, Slack's way: Messages, Pins, Files & links, Bookmarks and ＋ under its header. Every tab is about
// the conversation (what was said, shared and kept), never an agent's settings. Pins and bookmarks are read when the
// channel opens and again when a frame says they moved; files and links when their tab opens. Opening a pin or a
// shared file in the conversation jumps the timeline to its message and lights it for a moment.
import { useCallback, useEffect, useRef, useState, type ComponentType, type ReactNode, type Ref } from 'react';
import { toast } from 'sonner';
import { SiFigma, SiGithub, SiGoogle, SiGoogledocs, SiGooglesheets, SiLinear, SiNotion, SiStripe } from 'react-icons/si';
import { Bookmark, Copy, FileCode2, FileSpreadsheet, FileText, Globe, MessageSquareText, MoreHorizontal, Paperclip, Pin, PinOff, Plus, Search, Trash2, X } from 'lucide-react';
import { HAIRLINE } from '@/ui/primitives';
import { timeLabel } from '@/screens/channels/MessageList';
import { LogoMark, MARK_IN_A_SHAPE } from '@/ui/LogoMark';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { authorMember } from '@/screens/channels/model';
import type { ChannelAuthor, ChannelMember, ChannelMessage } from '@/screens/channels/types';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { useWorkFrames } from '@/sdk/live';
import { SidewaysRow } from '../ui';
import type { ChannelBookmark, ChannelPin, ChannelShelf, SharedFile, SharedLink } from './shelf';

export type ChannelView = 'messages' | 'pins' | 'files' | 'bookmarks';

const TAB_ICON: Record<ChannelView, typeof Pin> = { messages: MessageSquareText, pins: Pin, files: Paperclip, bookmarks: Bookmark };
const TAB_LABEL: Record<ChannelView, string> = { messages: 'Messages', pins: 'Pins', files: 'Files & links', bookmarks: 'Bookmarks' };
const CIRCLE =
    'grid h-8 w-8 shrink-0 place-items-center rounded-full max-md:h-10 max-md:w-10 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.07] data-[state=open]:text-foreground';
const LINKISH = 'rounded-full underline decoration-muted-foreground/40 underline-offset-2 transition-colors hover:text-foreground hover:decoration-foreground/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70';
const PILL =
    'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-foreground/85 ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 dark:ring-foreground/[0.12]';
const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');

interface Shared {
    files: SharedFile[];
    links: SharedLink[];
}

/** A channel's tabs and what they hold, for its pane. What they hold is read once `ready` (the channel's messages are
 *  in): read beside them, five reads slowed the one the pane waits on. */
export function useChannelTabs(channelId: string, shelf: ChannelShelf, compact = false, ready = true) {
    const [view, setView] = useState<ChannelView>('messages');
    const [adding, setAdding] = useState(false);
    const [pins, setPins] = useState<ChannelPin[]>([]);
    const [bookmarks, setBookmarks] = useState<ChannelBookmark[]>([]);
    const [shared, setShared] = useState<Shared | null>(null);
    const [jump, setJump] = useState<{ id: string; n: number } | null>(null);

    const readPins = useCallback(() => shelf.pins(channelId).then(setPins, (e) => console.warn('[work] pins failed:', e)), [shelf, channelId]);
    const readBookmarks = useCallback(() => shelf.bookmarks(channelId).then(setBookmarks, (e) => console.warn('[work] bookmarks failed:', e)), [shelf, channelId]);
    const readShared = useCallback(
        () =>
            Promise.all([shelf.files(channelId), shelf.links(channelId)]).then(
                ([files, links]) => setShared({ files, links }),
                (e) => console.warn('[work] files and links failed:', e)
            ),
        [shelf, channelId]
    );
    useEffect(() => {
        setView('messages');
        setPins([]);
        setBookmarks([]);
        setShared(null);
    }, [channelId]);
    useEffect(() => {
        if (!ready) return;
        void readPins();
        void readBookmarks();
        void readShared();
    }, [ready, readPins, readBookmarks, readShared]);
    useWorkFrames('platform:channel', (frame) => {
        if (frame.channel_id !== channelId) return;
        if (frame.kind === ('pin' as typeof frame.kind)) void readPins();
        else if (frame.kind === ('bookmark' as typeof frame.kind)) void readBookmarks();
        else if (frame.kind === 'message' || frame.kind === ('thread' as typeof frame.kind)) void readShared();
    });

    return {
        channelId,
        shelf,
        compact,
        view,
        setView,
        adding,
        setAdding,
        pins,
        bookmarks,
        shared,
        jump,
        /** Back to the timeline at a message. */
        open: (messageId: string) => {
            setView('messages');
            setJump({ id: messageId, n: Date.now() });
        },
        landed: () => setJump(null),
        /** Pin it or take the pin off; the message as it now stands, or null when it failed (and said why). */
        togglePin: async (messageId: string, on: boolean): Promise<ChannelMessage | null> => {
            try {
                const message = await shelf.pin(channelId, messageId, on);
                void readPins();
                return message;
            } catch (e) {
                toast.error(errorText(e));
                return null;
            }
        },
        addBookmark: async (bookmark: { url: string; title: string }) => {
            const made = await shelf.addBookmark(channelId, bookmark);
            setBookmarks((prev) => [...prev.filter((b) => b.id !== made.id), made]);
        },
        removeBookmark: async (bookmark: ChannelBookmark) => {
            setBookmarks((prev) => prev.filter((b) => b.id !== bookmark.id));
            try {
                await shelf.removeBookmark(channelId, bookmark.id);
                toast('Bookmark removed', {
                    description: bookmark.title,
                    action: { label: 'Undo', onClick: () => void shelf.addBookmark(channelId, { url: bookmark.url, title: bookmark.title }).then(() => readBookmarks()) },
                });
            } catch (e) {
                toast.error(errorText(e));
                void readBookmarks();
            }
        },
        searchShared: async (q: string): Promise<Shared> => {
            const [files, links] = await Promise.all([shelf.files(channelId, q), shelf.links(channelId, q)]);
            return { files, links };
        },
    };
}

export type ChannelTabs = ReturnType<typeof useChannelTabs>;

/** Under the channel's header: Messages, Pins, Files & links, Bookmarks, ＋. Scrolls sideways when narrow. */
export function ChannelTabBar({ tabs }: { tabs: ChannelTabs }) {
    const counts: Record<ChannelView, number> = { messages: 0, pins: tabs.pins.length, files: (tabs.shared?.files.length ?? 0) + (tabs.shared?.links.length ?? 0), bookmarks: tabs.bookmarks.length };
    const row = useRef<HTMLDivElement>(null);
    // When it's too narrow for every tab: the open one scrolled into sight, and a soft edge on either side hiding more.
    useEffect(() => {
        const el = row.current;
        const on = el?.querySelector<HTMLElement>('[aria-selected="true"]');
        if (el && on && (on.offsetLeft < el.scrollLeft || on.offsetLeft + on.offsetWidth > el.scrollLeft + el.clientWidth)) el.scrollLeft = on.offsetLeft - 8;
    }, [tabs.view]);
    return (
        <div className={cn('shrink-0 border-b', HAIRLINE)}>
            <SidewaysRow scrollRef={row} deps={[tabs.view]} role="tablist" aria-label="Channel" className={cn('flex items-center gap-0.5', tabs.compact ? 'px-1.5' : 'px-3')}>
                {(Object.keys(TAB_LABEL) as ChannelView[]).map((v) => {
                    const Icon = TAB_ICON[v];
                    const on = tabs.view === v;
                    return (
                        <button key={v} type="button" role="tab" aria-selected={on} onClick={() => tabs.setView(v)} className="group/tab relative flex h-10 shrink-0 items-center rounded-full px-0.5 focus-visible:outline-none">
                            <span
                                className={cn(
                                    'inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[13px] transition-colors group-hover/tab:bg-foreground/[0.05] group-focus-visible/tab:ring-2 group-focus-visible/tab:ring-ring/70',
                                    on ? 'font-medium text-foreground' : 'text-muted-foreground group-hover/tab:text-foreground'
                                )}
                            >
                                <Icon className="h-4 w-4" strokeWidth={on ? 2.1 : 1.8} />
                                {TAB_LABEL[v]}
                                {counts[v] > 0 && <span className="tabular-nums text-muted-foreground">{counts[v]}</span>}
                            </span>
                            {on && <span aria-hidden className="absolute inset-x-2.5 bottom-0 h-0.5 rounded-full bg-foreground" />}
                        </button>
                    );
                })}
                {/* Not modal, so the form it opens can take the focus while it closes. */}
                <DropdownMenu modal={false}>
                    <ShortcutTooltip label="Add to this channel">
                        {/* Open, it's marked by aria-expanded: the tooltip's trigger sets data-state over the menu's. */}
                        <DropdownMenuTrigger aria-label="Add to this channel" className={cn(CIRCLE, 'ml-0.5 aria-expanded:bg-foreground/[0.07] aria-expanded:text-foreground')}>
                            <Plus className="h-4 w-4" strokeWidth={2} />
                        </DropdownMenuTrigger>
                    </ShortcutTooltip>
                    {/* Closing leaves the focus in the form it opened, not back on ＋. */}
                    <DropdownMenuContent align="start" sideOffset={6} onCloseAutoFocus={(e) => e.preventDefault()} className="w-[260px] rounded-xl p-1">
                        <DropdownMenuItem
                            onSelect={() => {
                                tabs.setView('bookmarks');
                                tabs.setAdding(true);
                            }}
                            className="items-start gap-2.5 rounded-lg px-2.5 py-2 text-sm"
                        >
                            <Bookmark className="mt-0.5 h-4 w-4 text-muted-foreground" strokeWidth={1.9} />
                            <span>
                                <span className="block">Add a bookmark</span>
                                <span className="block text-xs text-muted-foreground">A link everyone here keeps at hand</span>
                            </span>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </SidewaysRow>
        </div>
    );
}

/** The tab that isn't Messages. On a laptop it covers the timeline (which keeps its place); on a phone it's the screen. */
export function ChannelTabBody({ tabs, members, renderMessage }: { tabs: ChannelTabs; members: ChannelMember[]; renderMessage: (m: ChannelMessage) => ReactNode }) {
    if (tabs.view === 'messages') return null;
    const body = (
        <div className={cn('w-full', tabs.compact ? 'px-1 pb-8 pt-3' : 'max-w-[60rem] px-2 pb-12 pt-4')}>
            {tabs.view === 'pins' && <PinsTab tabs={tabs} members={members} renderMessage={renderMessage} />}
            {tabs.view === 'files' && <FilesTab tabs={tabs} members={members} />}
            {tabs.view === 'bookmarks' && <BookmarksTab tabs={tabs} />}
        </div>
    );
    return (
        <div role="tabpanel" aria-label={TAB_LABEL[tabs.view]} className="absolute inset-0 z-20 overflow-y-auto bg-background scrollbar-subtle">
            {body}
        </div>
    );
}

/** An action a row shows on hover or focus on a laptop, and always on a phone. */
const rowAction = (compact: boolean) => (compact ? '' : 'opacity-0 transition-opacity group-hover/row:opacity-100 group-focus-within/row:opacity-100');

function OpenInConversation({ tabs, messageId }: { tabs: ChannelTabs; messageId: string }) {
    return tabs.compact ? (
        <ShortcutTooltip label="Open in conversation">
            <button type="button" aria-label="Open in conversation" onClick={() => tabs.open(messageId)} className={cn(CIRCLE, 'h-7 w-7')}>
                <MessageSquareText className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
        </ShortcutTooltip>
    ) : (
        <button type="button" onClick={() => tabs.open(messageId)} className={PILL}>
            <MessageSquareText className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
            Open in conversation
        </button>
    );
}

function Empty({ icon: Icon, title, note }: { icon: typeof Pin; title: string; note: string }) {
    return (
        <div className="flex flex-col items-center px-6 py-16 text-center">
            <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
                <Icon className="h-5 w-5 text-foreground/70" strokeWidth={1.8} />
            </span>
            <p className="mt-3 text-sm font-medium">{title}</p>
            <p className="mt-1 max-w-[22rem] text-[13px] leading-relaxed text-muted-foreground">{note}</p>
        </div>
    );
}

const nameOf = (author: ChannelAuthor, members: ChannelMember[]) => (author.type === 'account' && !author.id ? 'You' : (authorMember(author, members)?.name ?? (author.name || 'NoClick')));
const firstOf = (author: ChannelAuthor, members: ChannelMember[]) => nameOf(author, members).split(' ')[0];

function dayAndTime(iso: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    const day = d.toDateString() === today.toDateString() ? 'Today' : d.toDateString() === yesterday.toDateString() ? 'Yesterday' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return `${day} at ${timeLabel(iso)}`;
}

function PinsTab({ tabs, members, renderMessage }: { tabs: ChannelTabs; members: ChannelMember[]; renderMessage: (m: ChannelMessage) => ReactNode }) {
    if (!tabs.pins.length) return <Empty icon={Pin} title="Nothing pinned yet" note="Pin a message from its More menu, and everyone here finds it in this tab." />;
    return (
        <div className="space-y-1" data-testid="pins-tab">
            {tabs.pins.map((pin) => (
                <div key={pin.message.id} className="group/row rounded-xl pb-1 transition-colors hover:bg-foreground/[0.03] focus-within:bg-foreground/[0.03]">
                    <div className={cn('flex min-h-9 items-center gap-2 pr-2 pt-1.5 text-xs text-muted-foreground', tabs.compact ? 'pl-[60px]' : 'pl-[64px]')}>
                        <Pin className="h-3 w-3 shrink-0" strokeWidth={2} />
                        <span className="min-w-0 truncate">
                            Pinned by <span className="font-medium text-foreground/80">{firstOf(pin.by, members)}</span>
                            {pin.at && ` · ${dayAndTime(pin.at)}`}
                        </span>
                        <span className={cn('ml-auto flex shrink-0 items-center gap-1', rowAction(tabs.compact))}>
                            <OpenInConversation tabs={tabs} messageId={pin.message.id} />
                            <ShortcutTooltip label="Unpin from channel">
                                <button type="button" aria-label="Unpin from channel" onClick={() => void tabs.togglePin(pin.message.id, false)} className={cn(CIRCLE, 'h-7 w-7')}>
                                    <PinOff className="h-3.5 w-3.5" strokeWidth={2} />
                                </button>
                            </ShortcutTooltip>
                        </span>
                    </div>
                    {renderMessage({ ...pin.message, pinned: null, thread: undefined })}
                </div>
            ))}
        </div>
    );
}

// Files & links: what the channel's messages carry, newest first.

const hostOf = (url: string) => {
    try {
        return new URL(url).hostname.replace(/^www\./, '');
    } catch {
        return url;
    }
};
const extOf = (name: string) => (name.includes('.') ? name.split('.').pop()!.toUpperCase() : 'FILE');
const sizeOf = (bytes: number) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

function FilesTab({ tabs, members }: { tabs: ChannelTabs; members: ChannelMember[] }) {
    const [query, setQuery] = useState('');
    const [found, setFound] = useState<Shared | null>(null);
    const q = query.trim();
    // A search asks the channel, so it finds what's older than the first page too.
    useEffect(() => {
        if (!q) return setFound(null);
        let live = true;
        const timer = setTimeout(() => {
            tabs.searchShared(q).then(
                (result) => live && setFound(result),
                (e) => console.warn('[work] search failed:', e)
            );
        }, 200);
        return () => {
            live = false;
            clearTimeout(timer);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- the search reads the open channel's shelf
    }, [q, tabs.channelId]);
    const shown = (q ? found : tabs.shared) ?? { files: [], links: [] };
    if (!tabs.shared) return <p className="px-3 py-10 text-center text-[13px] text-muted-foreground">Reading what this channel shared…</p>;
    if (!tabs.shared.files.length && !tabs.shared.links.length) return <Empty icon={Paperclip} title="No files or links yet" note="Pictures, documents and links shared in this channel gather here, each with the message it came in." />;
    return (
        <div data-testid="files-tab">
            <div className={cn('pb-3', tabs.compact ? 'px-2' : 'max-w-[26rem] px-3')}>
                <SearchField value={query} onChange={setQuery} placeholder="Search files and links" />
            </div>
            {q && found && !shown.files.length && !shown.links.length && <p className="px-3 py-10 text-center text-[13px] text-muted-foreground">Nothing here matches “{q}”.</p>}
            {shown.files.length > 0 && (
                <Section label="Files" count={shown.files.length}>
                    {shown.files.map((s) => (
                        <ShareRow
                            key={`${s.messageId}:${s.file.id}`}
                            tabs={tabs}
                            messageId={s.threadId ?? s.messageId}
                            face={<FileTile name={s.file.name} url={s.file.kind === 'image' ? s.file.url : undefined} />}
                            title={s.file.name}
                            meta={`${nameOf(s.author, members)} · ${dayAndTime(s.at)} · ${extOf(s.file.name)} · ${sizeOf(s.file.sizeBytes)}`}
                            href={s.file.url}
                        />
                    ))}
                </Section>
            )}
            {shown.links.length > 0 && (
                <Section label="Links" count={shown.links.length}>
                    {shown.links.map((s) => (
                        <ShareRow
                            key={`${s.messageId}:${s.url}`}
                            tabs={tabs}
                            messageId={s.threadId ?? s.messageId}
                            face={<SiteTile url={s.url} />}
                            title={s.title ?? s.domain}
                            meta={`${s.domain} · ${nameOf(s.author, members)}, ${dayAndTime(s.at)}`}
                            href={s.url}
                        />
                    ))}
                </Section>
            )}
        </div>
    );
}

function Section({ label, count, children }: { label: string; count: number; children: ReactNode }) {
    return (
        <section className="pb-4">
            <p className="flex items-center gap-1.5 px-3 pb-1 pt-2 text-xs font-medium text-muted-foreground">
                {label}
                <span className="tabular-nums opacity-70">{count}</span>
            </p>
            {children}
        </section>
    );
}

function ShareRow({ tabs, messageId, face, title, meta, href }: { tabs: ChannelTabs; messageId: string; face: ReactNode; title: string; meta: string; href?: string }) {
    const inner = (
        <>
            {face}
            <span className="min-w-0">
                <span className="block truncate text-sm font-medium">{title}</span>
                <span className="block truncate text-xs text-muted-foreground">{meta}</span>
            </span>
        </>
    );
    const ROW = 'flex min-w-0 flex-1 items-center gap-3 rounded-xl py-2 pl-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70';
    return (
        <div className="group/row flex items-center gap-2 rounded-xl pr-2 transition-colors hover:bg-foreground/[0.04] focus-within:bg-foreground/[0.04]">
            {href ? (
                <a href={href} target="_blank" rel="noopener noreferrer" className={ROW}>
                    {inner}
                </a>
            ) : (
                <span className={ROW}>{inner}</span>
            )}
            <span className={rowAction(tabs.compact)}>
                <OpenInConversation tabs={tabs} messageId={messageId} />
            </span>
        </div>
    );
}

const TILE = 'grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-lg bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.07]';

function fileIcon(name: string) {
    const ext = extOf(name).toLowerCase();
    if (['csv', 'xls', 'xlsx', 'tsv'].includes(ext)) return FileSpreadsheet;
    if (['js', 'ts', 'tsx', 'py', 'json', 'log', 'sh', 'sql', 'html', 'css'].includes(ext)) return FileCode2;
    return FileText;
}

/** A file's tile: a picture's own thumbnail, else its kind's mark and extension. */
function FileTile({ name, url }: { name: string; url?: string }) {
    if (url) {
        return (
            <span className={TILE}>
                <img src={url} alt="" loading="lazy" className="h-full w-full object-cover" />
            </span>
        );
    }
    const Icon = fileIcon(name);
    return (
        <span className={cn(TILE, 'flex flex-col gap-0.5')}>
            <Icon className="h-[18px] w-[18px] text-foreground/75" strokeWidth={1.7} />
            <span className="text-[8px] font-semibold leading-none tracking-wide text-muted-foreground">{extOf(name).slice(0, 4)}</span>
        </span>
    );
}

const SITES: [RegExp, ComponentType<{ className?: string }>][] = [
    [/^docs\.google\.com\/spreadsheets/, SiGooglesheets],
    [/^docs\.google\.com/, SiGoogledocs],
    [/^(search|www)\.google\.com/, SiGoogle],
    [/^github\.com/, SiGithub],
    [/stripe\.com/, SiStripe],
    [/^linear\.app/, SiLinear],
    [/notion\.(so|site)/, SiNotion],
    [/figma\.com/, SiFigma],
];

/** A site's mark: its brand drawn in ink, NoClick's own, or a globe. */
function SiteMark({ url, className }: { url: string; className?: string }) {
    const host = hostOf(url);
    if (/(^|\.)noclick\.(com|app|run|email)$/.test(host)) return <LogoMark alt="" className={cn(className, MARK_IN_A_SHAPE)} />;
    const path = `${host}${url.replace(/^https?:\/\/[^/]+/, '')}`;
    const Icon = SITES.find(([re]) => re.test(path))?.[1] ?? Globe;
    return <Icon className={cn(className, 'text-foreground/80')} />;
}

function SiteTile({ url, small }: { url: string; small?: boolean }) {
    return (
        <span className={cn(TILE, small && 'h-8 w-8')}>
            <SiteMark url={url} className={small ? 'h-3.5 w-3.5' : 'h-4 w-4'} />
        </span>
    );
}

export function SearchField({ value, onChange, placeholder, inputRef }: { value: string; onChange: (v: string) => void; placeholder: string; inputRef?: Ref<HTMLInputElement> }) {
    return (
        <label className="flex h-9 items-center gap-2 rounded-full bg-foreground/[0.03] pl-3.5 pr-1 ring-1 ring-inset ring-border transition-shadow focus-within:ring-foreground/25 dark:ring-foreground/[0.09] dark:focus-within:ring-foreground/25">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
            <input ref={inputRef} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder} className="min-w-0 flex-1 bg-transparent text-[13.5px] outline-none placeholder:text-muted-foreground/70" />
            {value && (
                <button type="button" aria-label="Clear" onClick={() => onChange('')} className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                    <X className="h-3.5 w-3.5" strokeWidth={2} />
                </button>
            )}
        </label>
    );
}

// Bookmarks: links the channel keeps handy.

const INPUT =
    'h-10 w-full rounded-full bg-transparent px-4 text-[14px] text-foreground outline-none ring-1 ring-inset ring-border transition-shadow placeholder:text-muted-foreground/70 focus:ring-foreground/30 dark:ring-foreground/[0.1] dark:focus:ring-foreground/30';

/** A typed link as an address, https:// assumed; null when it isn't one. */
export function asUrl(text: string): string | null {
    const t = text.trim();
    if (!t || /\s/.test(t)) return null;
    try {
        const u = new URL(/^https?:\/\//i.test(t) ? t : `https://${t}`);
        return u.hostname.includes('.') ? u.toString() : null;
    } catch {
        return null;
    }
}

/** A name for a link before you give it one: its page's last words, else its site. */
export function guessTitle(url: string): string {
    try {
        const u = new URL(url);
        const parts = u.pathname.split('/').filter(Boolean);
        if (u.hostname === 'github.com' && parts.length >= 2) return `${parts[0]}/${parts[1]}`;
        const last = parts.filter((p) => !/^(d|u|edit|view|\d+|[A-Za-z0-9_]{12,})$/.test(p)).pop();
        if (last) {
            const words = decodeURIComponent(last).replace(/\.\w+$/, '').replace(/[-_]+/g, ' ').trim();
            if (words) return words[0].toUpperCase() + words.slice(1);
        }
        return u.hostname.replace(/^www\./, '');
    } catch {
        return url;
    }
}

function BookmarksTab({ tabs }: { tabs: ChannelTabs }) {
    return (
        <div data-testid="bookmarks-tab">
            {tabs.adding ? (
                <BookmarkForm tabs={tabs} />
            ) : (
                <button
                    type="button"
                    onClick={() => tabs.setAdding(true)}
                    className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-foreground/[0.04] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
                >
                    <span className="grid h-8 w-8 place-items-center rounded-full bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.07]">
                        <Plus className="h-4 w-4" strokeWidth={2} />
                    </span>
                    Add a bookmark
                </button>
            )}
            {tabs.bookmarks.length === 0 && !tabs.adding && <p className="px-3 pt-6 text-[13px] leading-relaxed text-muted-foreground">Keep the links this channel goes back to here: the plan, a dashboard, the preview.</p>}
            <div className="mt-1">
                {tabs.bookmarks.map((b) => (
                    <div key={b.id} className="group/row flex items-center gap-2 rounded-xl pr-2 transition-colors hover:bg-foreground/[0.04] focus-within:bg-foreground/[0.04]">
                        <a
                            href={b.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex min-w-0 flex-1 items-center gap-3 rounded-xl py-2 pl-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
                        >
                            <SiteTile url={b.url} small />
                            <span className="min-w-0">
                                <span className="block truncate text-sm font-medium">{b.title}</span>
                                <span className="block truncate text-xs text-muted-foreground">{hostOf(b.url)}</span>
                            </span>
                        </a>
                        <DropdownMenu>
                            <DropdownMenuTrigger aria-label={`More for ${b.title}`} className={cn(CIRCLE, 'h-7 w-7', !tabs.compact && 'opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100 data-[state=open]:opacity-100')}>
                                <MoreHorizontal className="h-4 w-4" />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" sideOffset={6} className="w-[200px] rounded-xl p-1">
                                <DropdownMenuItem
                                    onSelect={() =>
                                        navigator.clipboard.writeText(b.url).then(
                                            () => toast('Link copied'),
                                            () => toast('Couldn’t copy', { description: 'The browser refused the clipboard.' })
                                        )
                                    }
                                    className="gap-2.5 rounded-lg px-2.5 py-2 text-sm"
                                >
                                    <Copy className="h-4 w-4 text-muted-foreground" strokeWidth={1.9} />
                                    Copy link
                                </DropdownMenuItem>
                                <DropdownMenuSeparator className="mx-1 bg-border dark:bg-foreground/[0.08]" />
                                <DropdownMenuItem onSelect={() => void tabs.removeBookmark(b)} className="gap-2.5 rounded-lg px-2.5 py-2 text-sm text-red-600 dark:text-red-400">
                                    <Trash2 className="h-4 w-4" strokeWidth={1.9} />
                                    Remove
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                ))}
            </div>
        </div>
    );
}

/** Add a bookmark: the link first, then what to call it (a name is suggested from the link). */
function BookmarkForm({ tabs }: { tabs: ChannelTabs }) {
    const [text, setText] = useState('');
    const [url, setUrl] = useState<string | null>(null);
    const [title, setTitle] = useState('');
    const [tried, setTried] = useState(false);
    const [problem, setProblem] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const urlField = useRef<HTMLInputElement>(null);
    const titleField = useRef<HTMLInputElement>(null);
    // Each step's field takes the typing as it opens; the suggested name is selected, to keep or type over.
    useEffect(() => {
        if (url) titleField.current?.select();
        else urlField.current?.focus();
    }, [url]);
    const next = () => {
        const u = asUrl(text);
        setTried(true);
        if (!u) return;
        setUrl(u);
        setTitle(guessTitle(u));
    };
    const add = async () => {
        if (!url || busy) return;
        setBusy(true);
        setProblem(null);
        try {
            await tabs.addBookmark({ url, title: title.trim() || guessTitle(url) });
            tabs.setAdding(false);
            toast('Bookmark added', { description: 'Everyone in the channel sees it here.' });
        } catch (e) {
            setProblem(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    const cancel = () => tabs.setAdding(false);
    return (
        <form
            onSubmit={(e) => {
                e.preventDefault();
                if (url) void add();
                else next();
            }}
            className={cn('px-3 pb-4 pt-1', !tabs.compact && 'max-w-[30rem]')}
        >
            <p className="text-sm font-medium">Add a bookmark</p>
            {url ? (
                <>
                    <div className="mt-3 flex items-center gap-2.5">
                        <SiteTile url={url} small />
                        <span className="min-w-0 flex-1 truncate text-[13px] text-muted-foreground">{url.replace(/^https?:\/\//, '').replace(/\/$/, '')}</span>
                        <button type="button" onClick={() => setUrl(null)} className={cn(LINKISH, 'shrink-0 text-xs text-muted-foreground')}>
                            Change
                        </button>
                    </div>
                    <label className="mt-3 block text-xs font-medium text-muted-foreground" htmlFor="bookmark-title">
                        Name
                    </label>
                    <input id="bookmark-title" ref={titleField} value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && cancel()} className={cn(INPUT, 'mt-1.5')} />
                </>
            ) : (
                <>
                    <label className="mt-3 block text-xs font-medium text-muted-foreground" htmlFor="bookmark-url">
                        Link
                    </label>
                    <input
                        id="bookmark-url"
                        ref={urlField}
                        value={text}
                        onChange={(e) => {
                            setText(e.target.value);
                            setTried(false);
                        }}
                        onKeyDown={(e) => e.key === 'Escape' && cancel()}
                        placeholder="https://"
                        inputMode="url"
                        className={cn(INPUT, 'mt-1.5')}
                    />
                    {tried && !asUrl(text) && <p className="mt-1.5 px-1 text-xs text-red-600 dark:text-red-400">That doesn’t look like a link. Paste its whole address.</p>}
                </>
            )}
            {problem && (
                <p role="alert" className="mt-1.5 px-1 text-xs text-red-600 dark:text-red-400">
                    {problem}
                </p>
            )}
            <div className="mt-3 flex items-center gap-1.5">
                <button type="submit" disabled={busy || (url ? !title.trim() : !text.trim())} className={BUTTON_PRIMARY.replace('h-9', 'h-8')}>
                    {url ? 'Add bookmark' : 'Next'}
                </button>
                <button type="button" onClick={cancel} className={BUTTON_GHOST.replace('h-9', 'h-8')}>
                    Cancel
                </button>
            </div>
        </form>
    );
}
